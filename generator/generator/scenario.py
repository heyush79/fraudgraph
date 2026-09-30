"""One fraud episode, on demand, at a pace someone can watch.

    python -m generator.scenario ring --accounts 5 --gap-secs 15
    python -m generator.scenario geo
    python -m generator.scenario velocity
    python -m generator.scenario policy

The background generator plants episodes at random times, and a ring takes 10 to 30 minutes
to close, which is realistic and useless for showing anyone. A scenario publishes a single
episode starting now: the same user population, the same injectors and the same ground-truth
labels as the generator, compressed in time. It runs alongside the generator, never instead
of it, so the episode lands in ordinary traffic exactly as a random one would.

The last line on stdout is a JSON summary (users, transaction ids, episode id) that the
showcase recorder uses to find the resulting cases.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from .injectors.geo import GeoInjector
from .injectors.ring import RingInjector
from .injectors.velocity import VelocityInjector
from .models import ScheduledTxn, Transaction
from .publisher import KafkaPublisher, Publisher, StdoutPublisher
from .traffic import BaseTraffic
from .users import DEFAULT_USERS, build_population

log = logging.getLogger("scenario")

# The engine's demo sanctions list (stream-engine application.yml, fraudgraph.policy).
SANCTIONED_MERCHANT = "m_CRYPTO_0013"
# Must match the running generator, or scenario users would be strangers to the engine: the
# population is a pure function of its size and this seed (see Runner).
POPULATION_SEED = 42


def build_episode(kind: str, users, traffic: BaseTraffic, rng: random.Random, start: datetime,
                  accounts: int, gap_secs: float) -> list[ScheduledTxn]:
    if kind == "ring":
        minutes = accounts * gap_secs / 60.0
        # the injector spreads k hops over the duration with up to half a gap of jitter each
        return RingInjector(users, traffic, rng, accounts=(accounts, accounts), minutes=(minutes, minutes)).episode(start)
    if kind == "geo":
        # 90 seconds from home to a city over 1,000 km away: tens of thousands of km/h
        return GeoInjector(users, traffic, rng, gap_minutes=(1.5, 1.5), far_txns=(2, 2)).episode(start)
    if kind == "velocity":
        return VelocityInjector(users, traffic, rng).episode(start)
    if kind == "policy":
        user = rng.choice(users)
        base = traffic.make_transaction(user, start)
        txn = Transaction(txn_id=str(uuid.uuid4()), user_id=user.user_id, merchant_id=SANCTIONED_MERCHANT,
                          counterparty_id=None, amount=round(rng.uniform(1500.0, 9000.0), 2), currency="INR",
                          lat=base.lat, lon=base.lon, device_id=user.device_id,
                          channel=base.channel if base.channel.value != "P2P" else base.channel.CARD, ts=start)
        return [ScheduledTxn(at=start, txn=txn)]      # a policy breach, not a planted pattern: no label
    raise ValueError(f"unknown scenario {kind!r}")


def tag(episode: list[ScheduledTxn]) -> list[ScheduledTxn]:
    """Marks the labels as scenario-planted: still ground truth for training, but left out of
    recall measurements, which are about what the system finds in unscripted traffic."""
    return [replace(ev, label=replace(ev.label, source="scenario")) if ev.label is not None else ev
            for ev in episode]


def play(episode: list[ScheduledTxn], publisher: Publisher, sleep=time.sleep, now=lambda: datetime.now(timezone.utc)) -> None:
    """Publishes each event at its scheduled time. Event time is the schedule, so the engine
    sees the pace the scenario asked for even if this process is briefly late."""
    for ev in sorted(episode):
        delay = (ev.at - now()).total_seconds()
        if delay > 0:
            sleep(delay)
        publisher.publish_txn(ev.txn)
        if ev.label is not None:
            publisher.publish_label(ev.label)
        publisher.flush()
        cp = f" -> {ev.txn.counterparty_id}" if ev.txn.counterparty_id else f" @ {ev.txn.merchant_id}"
        log.info("%s %s%s  %.2f  %s", ev.at.strftime("%H:%M:%S"), ev.txn.user_id, cp, ev.txn.amount, ev.txn.txn_id)


def summary(kind: str, episode: list[ScheduledTxn]) -> dict:
    labels = [ev.label for ev in episode if ev.label is not None]
    return {
        "scenario": kind,
        "episodeId": labels[0].episode_id if labels else None,
        "users": sorted({ev.txn.user_id for ev in episode}),
        "txnIds": [ev.txn.txn_id for ev in sorted(episode)],
        "labelledTxnIds": [lbl.txn_id for lbl in labels],
        "startedAt": min(ev.at for ev in episode).isoformat(),
        "endedAt": max(ev.at for ev in episode).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="generator.scenario", description="publish one fraud episode now, compressed in time")
    ap.add_argument("kind", choices=["ring", "geo", "velocity", "policy"])
    ap.add_argument("--accounts", type=int, default=5, help="ring size (default 5)")
    ap.add_argument("--gap-secs", type=float, default=15.0, help="mean seconds between ring hops (default 15)")
    ap.add_argument("--users", type=int, default=int(os.environ.get("FRAUDGRAPH_USERS") or DEFAULT_USERS))
    ap.add_argument("--seed", type=int, default=None, help="pick the same accounts every time")
    ap.add_argument("--bootstrap-servers", default=os.environ.get("FRAUDGRAPH_BOOTSTRAP_SERVERS", "localhost:29092"))
    ap.add_argument("--dry-run", action="store_true", help="print events instead of publishing, without waiting")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", stream=sys.stderr)
    if args.kind == "ring" and args.accounts < 3:
        ap.error("a ring needs at least 3 accounts")

    rng = random.Random(args.seed)
    users = build_population(args.users, seed=POPULATION_SEED)
    traffic = BaseTraffic(users, 1.0, rng)
    start = datetime.now(timezone.utc) + timedelta(seconds=1)
    episode = tag(build_episode(args.kind, users, traffic, rng, start, args.accounts, args.gap_secs))
    if not episode:
        log.error("the injector produced no events (a geo scenario needs a far city); try again")
        return 1

    publisher: Publisher = StdoutPublisher() if args.dry_run else KafkaPublisher(args.bootstrap_servers)
    log.info("scenario %s: %d event(s) over %.0f s", args.kind, len(episode),
             (max(e.at for e in episode) - min(e.at for e in episode)).total_seconds())
    try:
        play(episode, publisher, sleep=(lambda _s: None) if args.dry_run else time.sleep)
    finally:
        publisher.close()
    print(json.dumps(summary(args.kind, episode)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
