from __future__ import annotations

import json
import pathlib
import random
from datetime import datetime, timedelta, timezone

import pytest

from generator.publisher import InMemoryPublisher
from generator.scenario import SANCTIONED_MERCHANT, build_episode, main, play, summary, tag
from generator.traffic import BaseTraffic
from generator.users import build_population

START = datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc)


@pytest.fixture
def world():
    rng = random.Random(7)
    users = build_population(500, seed=42)
    return users, BaseTraffic(users, 1.0, rng), rng


def test_a_ring_scenario_closes_within_minutes_and_is_labelled_hop_by_hop(world):
    users, traffic, rng = world
    ep = build_episode("ring", users, traffic, rng, START, accounts=5, gap_secs=15)
    assert len(ep) == 5
    assert [e.label.hop for e in ep] == [0, 1, 2, 3, 4] and {e.label.hops for e in ep} == {5}
    assert (ep[-1].at - START) <= timedelta(seconds=5 * 15)
    # it is a cycle: each hop pays the next account and the last pays the first back
    assert [e.txn.counterparty_id for e in ep] == [e.txn.user_id for e in ep[1:]] + [ep[0].txn.user_id]


def test_a_geo_scenario_jumps_cities_in_ninety_seconds(world):
    users, traffic, rng = world
    ep = build_episode("geo", users, traffic, rng, START, accounts=5, gap_secs=15)
    anchor, far = ep[0], ep[1:]
    assert anchor.label is None and len(far) == 2 and all(e.label is not None for e in far)
    assert far[0].at - anchor.at == timedelta(seconds=90)


def test_a_policy_scenario_pays_a_sanctioned_merchant_and_plants_no_label(world):
    users, traffic, rng = world
    [ev] = build_episode("policy", users, traffic, rng, START, accounts=5, gap_secs=15)
    assert ev.txn.merchant_id == SANCTIONED_MERCHANT and ev.label is None
    assert ev.txn.channel.value != "P2P"


def test_the_sanctioned_merchant_is_on_the_engines_list():
    yml = pathlib.Path(__file__).resolve().parents[2] / "stream-engine/src/main/resources/application.yml"
    if not yml.exists():
        pytest.skip("stream-engine config not present")
    assert SANCTIONED_MERCHANT in yml.read_text()


def test_play_publishes_in_time_order_with_labels(world):
    users, traffic, rng = world
    ep = build_episode("ring", users, traffic, rng, START, accounts=4, gap_secs=10)
    pub = InMemoryPublisher()
    slept: list[float] = []
    play(list(reversed(ep)), pub, sleep=slept.append, now=lambda: START)
    assert [t.txn_id for t in pub.txns] == [e.txn.txn_id for e in ep]
    assert len(pub.labels) == 4 and all(s >= 0 for s in slept)


def test_summary_names_the_episode_and_its_accounts(world):
    users, traffic, rng = world
    ep = build_episode("ring", users, traffic, rng, START, accounts=4, gap_secs=10)
    s = summary("ring", ep)
    assert s["episodeId"].startswith("ep_") and len(s["users"]) == 4
    assert s["labelledTxnIds"] == s["txnIds"]


def test_the_cli_dry_run_prints_a_json_summary_last(capsys):
    assert main(["ring", "--accounts", "4", "--gap-secs", "1", "--users", "300", "--seed", "3", "--dry-run"]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(last)["scenario"] == "ring"


def test_scenario_labels_are_tagged_and_background_labels_are_not(world):
    users, traffic, rng = world
    ep = tag(build_episode("ring", users, traffic, rng, START, accounts=4, gap_secs=10))
    assert all(json.loads(e.label.to_json())["source"] == "scenario" for e in ep)
    untagged = build_episode("ring", users, traffic, rng, START, accounts=4, gap_secs=10)
    assert all("source" not in json.loads(e.label.to_json()) for e in untagged)


def test_tagging_leaves_unlabelled_events_alone(world):
    users, traffic, rng = world
    ep = tag(build_episode("geo", users, traffic, rng, START, accounts=5, gap_secs=15))
    assert ep[0].label is None
