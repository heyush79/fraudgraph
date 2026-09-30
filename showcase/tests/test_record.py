from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from record import (describe, parse_instant, pattern_of, pick_featured, suggested_questions, ticks_to_feed,
                    window_stats, write_atomically)

START = datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc)


def tick(txn: str, secs: float, verdict: str = "ALLOW", **kw) -> dict:
    decided = START + timedelta(seconds=secs)
    return {"txnId": txn, "userId": "u_1", "verdict": verdict, "mode": "FULL", "mlScore": kw.get("score"),
            "firedRules": kw.get("rules", []), "latencyMs": 12,
            "decidedAt": decided.strftime("%Y-%m-%dT%H:%M:%S.") + f"{decided.microsecond:06d}123Z",
            "caseId": kw.get("case")}


def test_java_nanosecond_instants_parse():
    assert parse_instant("2026-09-29T15:32:20.452010044Z") == datetime(2026, 9, 29, 15, 32, 20, 452010, tzinfo=timezone.utc)
    assert parse_instant("2026-09-29T15:32:20Z").second == 20


def test_the_feed_keeps_only_the_window_in_order_without_duplicates():
    ticks = [tick("b", 2.5), tick("old", -30), tick("a", 1.0, score=0.999876), tick("b", 2.5), tick("late", 61)]
    feed = ticks_to_feed(ticks, START, START + timedelta(seconds=60))
    assert [t["txnId"] for t in feed] == ["a", "b"]
    assert [t["at"] for t in feed] == [1000, 2500]
    assert feed[0]["mlScore"] == 0.9999 and feed[0]["decidedAt"].endswith(".000Z")


def test_the_pattern_question_comes_right_after_why():
    qs = suggested_questions(["PASS_THROUGH", "RING_SUSPECT"])
    assert qs[:2] == ["Why was this transaction flagged?", "Where did the money come from, and where did it go?"]
    assert suggested_questions(["VELOCITY_1M"], limit=3) == [
        "Why was this transaction flagged?", "Could this be a genuine shopping spree?",
        "What evidence would change the verdict?"]
    assert suggested_questions([]) == ["Why was this transaction flagged?", "What evidence would change the verdict?",
                                       "Is this normal behaviour for this account?"]


def test_patterns_follow_the_strongest_rule():
    assert pattern_of(["VELOCITY_1M", "RING_SUSPECT"]) == "RING"
    assert pattern_of(["PASS_THROUGH"]) == "RING"
    assert pattern_of(["AMOUNT_CAP"]) is None


def test_featured_prefers_the_scenarios_own_cases_and_falls_back_to_rules():
    window = [
        {"caseId": "c-geo-random", "txnId": "t9", "firedRules": ["GEO_IMPOSSIBLE"]},
        {"caseId": "c-ring-close", "txnId": "r5", "firedRules": ["RING_SUSPECT", "PASS_THROUGH"]},
        {"caseId": "c-ring-mid", "txnId": "r3", "firedRules": ["PASS_THROUGH"]},
        {"caseId": "c-vel", "txnId": "v1", "firedRules": ["VELOCITY_1M"]},
    ]
    ring = {"scenario": "ring", "labelledTxnIds": ["r1", "r2", "r3", "r4", "r5"], "users": ["a", "b"]}
    chosen = pick_featured(window, [ring])
    assert list(chosen) == ["RING", "GEO", "VELOCITY"]              # contract order
    assert chosen["RING"] == {"caseId": "c-ring-close", "scenario": ring}
    assert chosen["GEO"]["caseId"] == "c-geo-random" and chosen["GEO"]["scenario"] is None


def test_a_ring_blurb_is_written_from_what_was_recorded():
    decision = {"mlScore": 0.97, "signals": [{"code": "RING_SUSPECT", "evidence": {
        "cycle": ["u_1", "u_2", "u_3", "u_4", "u_1"]}}]}
    scenario = {"labelledTxnIds": ["r1", "r2", "r3", "r4"], "users": ["u_1", "u_2", "u_3", "u_4"],
                "startedAt": START.isoformat(), "endedAt": (START + timedelta(seconds=61)).isoformat()}
    feed = [tick("r1", 1), tick("r2", 15, "REVIEW"), tick("r3", 30, "REVIEW"), tick("r4", 45, "BLOCK")]
    title, blurb = describe("RING", decision, scenario, feed, [])
    assert title == "A 4-account laundering ring"
    assert blurb == ("Money went u_1 → u_2 → u_3 → u_4 → u_1 in 1 minute. "
                     "The engine flagged 3 of 4 transfers, from transfer 2 on, before the ring closed.")


def test_a_geo_title_names_the_cities_when_it_can():
    decision = {"mlScore": 0.9990, "signals": [{"code": "GEO_IMPOSSIBLE", "evidence": {
        "fromLat": 28.63, "fromLon": 77.19, "toLat": 13.10, "toLon": 80.29, "gapSecs": 192,
        "speedKmh": 32929.3, "distanceKm": 1756.2}}]}
    cities = [("Delhi", 28.6139, 77.2090), ("Chennai", 13.0827, 80.2707)]
    title, blurb = describe("GEO", decision, None, [], cities)
    assert title == "Delhi, then Chennai, 3 minutes later"
    assert blurb == "The same card paid again 3 minutes later, 1,756 km away in Chennai: 32,929 km/h. The model scored it 0.9990."
    assert describe("GEO", decision, None, [], [])[0] == "1,756 km in 3 minutes"


def test_window_stats_describe_the_recording_not_all_time():
    s = window_stats([{"status": "OPEN", "verdict": "BLOCK"}, {"status": "OPEN", "verdict": "REVIEW"}])
    assert s == {"byStatus": {"OPEN": 2}, "total": 2, "last1h": {"cases": 2, "review": 1, "block": 1}}


def test_a_new_recording_replaces_the_old_one_whole(tmp_path):
    out = tmp_path / "showcase"
    write_atomically(out, {"manifest.json": {"v": 1}, "cases/a.json": {}})
    write_atomically(out, {"manifest.json": {"v": 2}})
    assert json.loads((out / "manifest.json").read_text()) == {"v": 2}
    assert not (out / "cases").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["showcase"]


def test_short_gaps_read_in_seconds():
    decision = {"signals": [{"code": "GEO_IMPOSSIBLE", "evidence": {"gapSecs": 90, "speedKmh": 50000.0, "distanceKm": 1250.0}}]}
    assert describe("GEO", decision, None, [], [])[0] == "1,250 km in 90 seconds"
