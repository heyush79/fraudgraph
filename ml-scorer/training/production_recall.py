"""Production recall: what the running system actually caught, not what the model could.

    python -m training.production_recall --hours 1

The threshold sweep in evaluate.py scores EVERY row offline. Production does not: the engine
only consults the model when a rule-based signal has already fired (or a 1% shadow sample
hits). A fraud pattern that fires no signal is therefore never scored, and the model's
offline recall on it says nothing about what happens to real traffic. This tool reads the
verdicts the engine actually emitted on `fraud.decisions`, joins them to the generator's
ground truth on `transactions.labels`, and reports what fraction of each pattern was flagged.

For rings it also reports recall by HOP POSITION within an episode, because a ring is only
detectably a ring once it closes: the first hop of A→B→C→A is an ordinary transfer, and the
question worth answering is how many hops before the closing one get caught.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .kafka_source import read_topic

log = logging.getLogger("production_recall")

DECISIONS_TOPIC = "fraud.decisions"
LABELS_TOPIC = "transactions.labels"
FLAGGED = ("REVIEW", "BLOCK")
# the ring injector spreads an episode over at most 30 minutes, plus jitter
RING_MAX_SECS = 32 * 60


def _older_than(ts: str, newest: str, secs: int) -> bool:
    try:
        a = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        b = datetime.fromisoformat(newest.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (b - a).total_seconds() >= secs
HARD_RULES = ("HARD_BLOCK_MERCHANT", "AMOUNT_CAP")


def load(bootstrap: str, hours: float, since: datetime | None = None,
         until: datetime | None = None) -> tuple[dict[str, dict], dict[str, dict]]:
    """Decisions keyed by txnId (only the fields this report needs) and labels keyed by txnId.
    `since` and `until` pin the window exactly, e.g. from the moment a new engine went live to
    the moment the host went to sleep, so a before/after comparison never mixes the two and
    never spans a gap in the traffic; otherwise the window is the last `hours`."""
    since = since or datetime.now(timezone.utc) - timedelta(hours=hours)
    lo = since.timestamp() * 1000
    hi = until.timestamp() * 1000 if until else float("inf")
    decisions: dict[str, dict] = {}
    for msg in read_topic(bootstrap, DECISIONS_TOPIC, since=since):
        if not lo <= msg.ts_ms < hi:
            continue                           # offsets-for-time seeks per partition; trim exactly
        d = json.loads(msg.value)
        decisions[d["txnId"]] = {
            "verdict": d.get("verdict"),
            "mode": d.get("mode"),
            "firedRules": d.get("firedRules") or [],
            "mlScore": d.get("mlScore"),
        }
    labels: dict[str, dict] = {}
    for msg in read_topic(bootstrap, LABELS_TOPIC, since=since - timedelta(hours=1)):
        if msg.ts_ms >= hi:
            continue
        lbl = json.loads(msg.value)
        if lbl.get("isFraud"):
            labels[lbl["txnId"]] = lbl
    return decisions, labels


def drop_scenarios(decisions: dict[str, dict], labels: dict[str, dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Fraud a person planted to watch (generator.scenario) is neither found fraud nor legit
    traffic: it leaves both sides of the measurement."""
    staged = {t for t, lbl in labels.items() if lbl.get("source") == "scenario"}
    return ({t: d for t, d in decisions.items() if t not in staged},
            {t: lbl for t, lbl in labels.items() if t not in staged})



def report(decisions: dict[str, dict], labels: dict[str, dict]) -> dict[str, Any]:
    """Pure function of the two joined sets, so it is testable without Kafka."""
    per_pattern: dict[str, Counter] = defaultdict(Counter)
    scored_per_pattern: dict[str, Counter] = defaultdict(Counter)
    episodes: dict[str, list[tuple[str, str]]] = defaultdict(list)

    matched = 0
    for txn_id, lbl in labels.items():
        d = decisions.get(txn_id)
        if d is None:
            continue                          # label outside the decision window
        matched += 1
        pattern = lbl.get("pattern", "UNKNOWN")
        verdict = d["verdict"]
        per_pattern[pattern][verdict] += 1
        # was the model even consulted? mlScore is null when it was not
        scored_per_pattern[pattern]["scored" if d.get("mlScore") is not None else "not_scored"] += 1
        if pattern == "RING":
            episodes[lbl.get("episodeId", "?")].append((lbl.get("ts", ""), verdict, lbl.get("hop"), lbl.get("hops")))

    recall = {}
    for pattern, verdicts in sorted(per_pattern.items()):
        n = sum(verdicts.values())
        flagged = sum(verdicts[v] for v in FLAGGED)
        scored = scored_per_pattern[pattern]["scored"]
        recall[pattern] = {
            "n": n,
            "recall": round(flagged / n, 4) if n else None,
            "verdicts": dict(verdicts),
            "modelConsulted": round(scored / n, 4) if n else None,
        }

    # Ring recall by hop position, over COMPLETE episodes only. A ring still in progress when the
    # window ends has no closing hop yet, and labelling its last observed hop "closing" would
    # measure nothing. Labels from newer generators carry hop/hops, which makes this exact;
    # older ones fall back to requiring every hop of a >= 3-hop episode be at least
    # RING_MAX_SECS old at the end of the window.
    by_position: dict[str, list[bool]] = defaultdict(list)
    # the end of the observation window: the newest label of ANY pattern that has a decision
    newest = max((lbl.get("ts", "") for t, lbl in labels.items() if t in decisions), default="")
    complete = 0
    for hops in episodes.values():
        hops.sort(key=lambda h: h[0])
        declared = hops[0][3]
        if declared is not None:
            if len(hops) != declared:
                continue                       # partly outside the window
            for ts, verdict, hop, total in hops:
                slot = "first" if hop == 0 else ("closing" if hop == total - 1 else "middle")
                by_position[slot].append(verdict in FLAGGED)
            complete += 1
            continue
        if len(hops) < 3 or not _older_than(hops[0][0], newest, RING_MAX_SECS):
            continue
        last = len(hops) - 1
        for i, (_, verdict, _, _) in enumerate(hops):
            slot = "first" if i == 0 else ("closing" if i == last else "middle")
            by_position[slot].append(verdict in FLAGGED)
        complete += 1
    ring_positions = {
        slot: {"n": len(hits), "recall": round(sum(hits) / len(hits), 4) if hits else None}
        for slot, hits in (("first", by_position["first"]), ("middle", by_position["middle"]),
                           ("closing", by_position["closing"]))
    }

    # the other side of the ledger: how much legitimate traffic got flagged, and why
    legit_total = 0
    legit_flagged_policy = 0
    legit_flagged_stat = 0
    modes: Counter = Counter()
    for txn_id, d in decisions.items():
        modes[d.get("mode")] += 1
        if txn_id in labels:
            continue
        legit_total += 1
        if d["verdict"] in FLAGGED:
            if any(r in HARD_RULES for r in d["firedRules"]):
                legit_flagged_policy += 1
            else:
                legit_flagged_stat += 1

    return {
        "decisions": len(decisions),
        "labelled": matched,
        "modes": dict(modes),
        "recallPerPattern": recall,
        "ringRecallByHop": ring_positions,
        "ringEpisodes": complete,
        "legit": {
            "n": legit_total,
            # policy flags are correct even without a label: a sanctioned merchant is a breach
            "flaggedPolicy": legit_flagged_policy,
            # the true false-positive rate is the statistical part
            "falsePositiveRate": round(legit_flagged_stat / legit_total, 5) if legit_total else None,
        },
    }


def format_report(r: dict[str, Any]) -> str:
    lines = [
        f"{r['decisions']:,} decisions, {r['labelled']:,} of them planted fraud. Modes: {r['modes']}",
        "",
        f"{'pattern':<10} {'n':>6} {'recall':>7} {'model consulted':>16}   verdicts",
    ]
    for pattern, s in r["recallPerPattern"].items():
        lines.append(f"{pattern:<10} {s['n']:>6} {s['recall']:>7.1%} {s['modelConsulted']:>16.1%}   {s['verdicts']}")
    lines += ["", f"ring recall by hop position ({r['ringEpisodes']} complete episodes):"]
    for slot, s in r["ringRecallByHop"].items():
        if s["n"]:
            lines.append(f"  {slot:<8} {s['n']:>5} hops   recall {s['recall']:.1%}")
    legit = r["legit"]
    lines += ["",
              f"legitimate traffic: {legit['n']:,} decisions, "
              f"{legit['flaggedPolicy']:,} flagged by policy rules (correct), "
              f"false-positive rate {legit['falsePositiveRate']:.3%}"
              if legit["falsePositiveRate"] is not None else "legitimate traffic: none"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="what the running system actually caught, per fraud pattern")
    ap.add_argument("--bootstrap-servers", default=os.environ.get("FRAUDGRAPH_BOOTSTRAP_SERVERS", "localhost:29092"))
    ap.add_argument("--hours", type=float, default=1.0)
    ap.add_argument("--since", type=lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")), default=None,
                    help="window start as ISO time (e.g. when a new engine went live); overrides --hours")
    ap.add_argument("--until", type=lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")), default=None,
                    help="window end as ISO time (e.g. when the host went to sleep); default now")
    ap.add_argument("--json", action="store_true", help="print the raw report as JSON")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    decisions, labels = drop_scenarios(*load(args.bootstrap_servers, args.hours, args.since, args.until))
    r = report(decisions, labels)
    print(json.dumps(r, indent=2) if args.json else format_report(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
