"""The production-recall report, on hand-built joins, with no Kafka."""
from __future__ import annotations

from training.production_recall import format_report, report


def dec(verdict, *, mode="FULL", rules=(), score=None):
    return {"verdict": verdict, "mode": mode, "firedRules": list(rules), "mlScore": score}


def lbl(pattern, episode="e1", ts="2026-09-29T10:00:00Z"):
    return {"isFraud": True, "pattern": pattern, "episodeId": episode, "ts": ts}


def test_recall_counts_review_and_block_as_caught():
    decisions = {"v1": dec("BLOCK", score=0.99), "v2": dec("REVIEW", score=0.7), "v3": dec("ALLOW")}
    labels = {"v1": lbl("VELOCITY"), "v2": lbl("VELOCITY"), "v3": lbl("VELOCITY")}
    r = report(decisions, labels)
    s = r["recallPerPattern"]["VELOCITY"]
    assert s["n"] == 3
    assert s["recall"] == 0.6667
    assert s["modelConsulted"] == 0.6667          # the ALLOW was never scored
    assert s["verdicts"] == {"BLOCK": 1, "REVIEW": 1, "ALLOW": 1}


def lbl_hop(i, n, episode="ep1"):
    return {**lbl("RING", episode, f"2026-09-29T10:0{i}:00Z"), "hop": i, "hops": n}


def test_ring_recall_is_broken_down_by_hop_position():
    """The closing hop fires RING_SUSPECT; the hops before it look like ordinary transfers."""
    decisions = {f"h{i}": dec("ALLOW") for i in range(4)}
    decisions["h4"] = dec("REVIEW", rules=["RING_SUSPECT"], score=0.8)
    labels = {f"h{i}": lbl_hop(i, 5) for i in range(5)}
    r = report(decisions, labels)
    assert r["ringEpisodes"] == 1
    assert r["ringRecallByHop"]["first"] == {"n": 1, "recall": 0.0}
    assert r["ringRecallByHop"]["middle"] == {"n": 3, "recall": 0.0}
    assert r["ringRecallByHop"]["closing"] == {"n": 1, "recall": 1.0}
    assert r["recallPerPattern"]["RING"]["recall"] == 0.2


def test_an_episode_still_in_progress_is_left_out_of_the_hop_breakdown():
    """Its last observed hop is not its closing hop yet, and calling it one would measure nothing."""
    decisions = {"a": dec("ALLOW"), "b": dec("ALLOW"), "c": dec("ALLOW")}
    labels = {k: lbl_hop(i, 6, "ep9") for i, k in enumerate("abc")}    # 3 of 6 hops so far
    r = report(decisions, labels)
    assert r["ringEpisodes"] == 0
    assert r["ringRecallByHop"]["closing"]["n"] == 0
    assert r["recallPerPattern"]["RING"]["n"] == 3   # still counted in overall recall


def test_old_labels_without_hop_positions_need_the_episode_to_be_old_enough():
    decisions = {f"h{i}": dec("ALLOW") for i in range(4)} | {"late": dec("ALLOW")}
    labels = {f"h{i}": lbl("RING", "old", f"2026-09-29T10:0{i}:00Z") for i in range(4)}
    labels["late"] = lbl("VELOCITY", "v", "2026-09-29T10:50:00Z")      # window runs 50 minutes past the ring
    assert report(decisions, labels)["ringEpisodes"] == 1
    young = {f"h{i}": lbl("RING", "young", f"2026-09-29T10:4{i}:00Z") for i in range(4)} | {"late": labels["late"]}
    assert report(decisions, young)["ringEpisodes"] == 0


def test_policy_flags_on_legit_traffic_are_not_false_positives():
    decisions = {
        "ok1": dec("ALLOW"), "ok2": dec("ALLOW"), "ok3": dec("ALLOW"),
        "pol": dec("BLOCK", rules=["HARD_BLOCK_MERCHANT"]),
        "fp": dec("REVIEW", rules=["GEO_IMPOSSIBLE"], score=0.7),
    }
    r = report(decisions, {})
    assert r["legit"]["n"] == 5
    assert r["legit"]["flaggedPolicy"] == 1
    assert r["legit"]["falsePositiveRate"] == 0.2       # only the geo one


def test_labels_outside_the_decision_window_are_ignored():
    r = report({"x": dec("BLOCK")}, {"x": lbl("GEO"), "gone": lbl("GEO")})
    assert r["labelled"] == 1
    assert r["recallPerPattern"]["GEO"]["n"] == 1


def test_the_text_report_renders():
    decisions = {f"h{i}": dec("ALLOW") for i in range(3)} | {"v": dec("BLOCK", score=0.99)}
    labels = {f"h{i}": lbl_hop(i, 3, "e") for i in range(3)} | {"v": lbl("VELOCITY")}
    text = format_report(report(decisions, labels))
    assert "ring recall by hop position" in text
    assert "VELOCITY" in text and "RING" in text


def test_since_trims_decisions_before_the_window_exactly(monkeypatch):
    """A before/after comparison must not mix the two engines: decisions stamped before
    --since are dropped even when the per-partition seek returns them."""
    import json as _json
    from datetime import datetime, timezone
    from training import production_recall as pr
    from training.kafka_source import Message
    since = datetime(2026, 9, 29, 16, 24, 30, tzinfo=timezone.utc)
    cut = int(since.timestamp() * 1000)

    def fake_read(bootstrap, topic, since=None, **kw):
        if topic == pr.DECISIONS_TOPIC:
            for txn, ts in (("before", cut - 1), ("after", cut + 1)):
                yield Message(None, _json.dumps({"txnId": txn, "verdict": "ALLOW"}).encode(), ts)
        return

    monkeypatch.setattr(pr, "read_topic", fake_read)
    decisions, labels = pr.load("x", 1.0, since)
    assert list(decisions) == ["after"] and labels == {}
    # and --until closes the window: nothing at or after it counts
    from datetime import timedelta
    decisions, _ = pr.load("x", 1.0, since, until=since + timedelta(milliseconds=1))
    assert list(decisions) == []


def test_scenario_fraud_leaves_both_sides_of_the_measurement():
    from training.production_recall import drop_scenarios
    decisions = {"staged": {"verdict": "BLOCK"}, "found": {"verdict": "REVIEW"}, "legit": {"verdict": "ALLOW"}}
    labels = {"staged": {"pattern": "RING", "source": "scenario"}, "found": {"pattern": "RING"}}
    d, lbl = drop_scenarios(decisions, labels)
    assert set(d) == {"found", "legit"} and set(lbl) == {"found"}
