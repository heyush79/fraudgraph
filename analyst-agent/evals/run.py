"""Agent eval harness (LLD §6.3).

The generator knows which transactions it planted, so evaluation needs no human labelling:
for each injected pattern, did the report's `fraud_type` match what was actually injected,
how many tool calls did it need, and did its citations survive the verify node.

    python -m evals.run --limit 40 --hours 6

Ground truth comes from `transactions.labels`, which the engine never reads. A case whose
transaction is absent from that topic was flagged on legitimate traffic, so it is scored on
a different question: did the agent decline to confirm it.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import statistics
import sys
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger("evals")

LABELS_TOPIC = "transactions.labels"
# The engine emits five signal codes; the report schema has five fraud types. These are the
# ones ground truth can actually distinguish.
PATTERNS = ("VELOCITY", "GEO", "RING")


def read_labels(bootstrap: str, hours: float) -> dict[str, str]:
    """txnId -> injected pattern, for the window. Bounded read to the high watermark."""
    from confluent_kafka import Consumer, TopicPartition

    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": f"fraudgraph-evals-{uuid.uuid4().hex[:8]}",
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    })
    labels: dict[str, str] = {}
    try:
        md = consumer.list_topics(LABELS_TOPIC, timeout=10)
        if LABELS_TOPIC not in md.topics:
            raise RuntimeError(f"topic {LABELS_TOPIC} not found; is the stack running?")
        parts = [TopicPartition(LABELS_TOPIC, p) for p in md.topics[LABELS_TOPIC].partitions]
        high = {tp.partition: consumer.get_watermark_offsets(tp, timeout=10)[1] for tp in parts}
        since_ms = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp() * 1000)
        starts = consumer.offsets_for_times(
            [TopicPartition(LABELS_TOPIC, tp.partition, since_ms) for tp in parts], timeout=10)
        assign = [TopicPartition(LABELS_TOPIC, tp.partition,
                                 tp.offset if tp.offset >= 0 else high[tp.partition]) for tp in starts]
        pending = {tp.partition for tp in assign if tp.offset < high[tp.partition]}
        consumer.assign(assign)
        idle = 0.0
        while pending and idle < 10.0:
            msg = consumer.poll(1.0)
            if msg is None:
                idle += 1.0
                continue
            idle = 0.0
            if msg.error():
                continue
            if msg.offset() + 1 >= high[msg.partition()]:
                pending.discard(msg.partition())
            doc = json.loads(msg.value())
            if doc.get("isFraud"):
                labels[doc["txnId"]] = doc.get("pattern", "UNKNOWN")
    finally:
        consumer.close()
    return labels


def fetch_cases(case_service: str, limit: int, rule: str | None = None) -> list[dict[str, Any]]:
    """Filtering is done by the API, not here. RING_SUSPECT is ~1% of cases, so paging recent
    cases and discarding the rest reaches three rings where the database holds eighty."""
    out: list[dict[str, Any]] = []
    params: dict[str, Any] = {"rule": rule} if rule else {}
    with httpx.Client(base_url=case_service, timeout=20) as http:
        offset = 0
        while len(out) < limit:
            page = http.get("/cases", params={**params, "limit": min(200, limit - len(out)), "offset": offset}).json()
            items = page.get("items") or []
            if not items:
                break
            out.extend(items)
            offset += len(items)
            if offset >= page.get("total", 0):
                break
    return out[:limit]


def investigate(agent: str, case_id: str, timeout: float) -> dict[str, Any] | None:
    try:
        with httpx.Client(base_url=agent, timeout=timeout) as http:
            r = http.post("/investigate/sync", json={"caseId": case_id})
            r.raise_for_status()
            return r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("case %s: %s", case_id, e)
        return None


def starved(result: dict[str, Any]) -> bool:
    """True when the provider never answered, so the agent had nothing to reason with.

    Groq's free tier allows 200,000 tokens per day, which is roughly 25 cases. Past that
    every model call returns 429 and the graph escalates as UNCERTAIN, exactly as designed.
    Counting those as wrong answers would report a quota as a quality measurement, so they
    are excluded from accuracy and reported on their own line.
    """
    notes = " | ".join(result.get("notes") or [])
    # "model call failed" appears for both the investigate and the draft phase; either one
    # means the provider never answered. "drafted" means a report was produced despite it,
    # so the case does measure the agent.
    return "model call failed" in notes and "draft_report: drafted" not in notes


HARD_RULES = ("HARD_BLOCK_MERCHANT", "AMOUNT_CAP")


def classify(result: dict[str, Any]) -> str:
    """What question this case can actually answer.

    - `planted`: the generator injected it, so the right call is to confirm.
    - `policy`: a hard rule fired and the generator planted nothing. A payment to a
      sanctioned merchant is a policy breach, not a pattern, so confirming it is correct
      even though there is no ground-truth label. Scoring these as "should have declined"
      penalises the agent for being right, which the first version of this harness did.
    - `falsePositive`: the engine flagged legitimate traffic on a statistical signal. The
      right call is to release or escalate, and this is the only group where declining is
      the correct answer.
    """
    if result.get("truth"):
        return "planted"
    fired = result.get("firedRules") or []
    return "policy" if any(r in HARD_RULES for r in fired) else "falsePositive"


def correct_action(kind: str, action: str | None) -> bool | None:
    if action is None:
        return None
    if kind in ("planted", "policy"):
        return action == "CONFIRM_BLOCK"
    return action in ("RELEASE", "ESCALATE")


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Accuracy per injected pattern, plus how the agent behaved on unplanted cases.

    Cases the provider starved are excluded from every quality metric and counted separately.
    """
    n_starved = sum(1 for r in results if starved(r))
    results = [r for r in results if not starved(r)]

    per_pattern: dict[str, list[bool]] = defaultdict(list)
    confusion: Counter = Counter()
    tool_calls: list[int] = []
    verified = 0
    escalated_uncertain = 0
    kinds: Counter = Counter()
    action_hits: dict[str, list[bool]] = defaultdict(list)

    for r in results:
        report = r.get("report") or {}
        v = report.get("verification") or {}
        predicted = report.get("fraud_type")
        truth = r.get("truth")
        kind = classify(r)
        kinds[kind] += 1

        if v.get("toolCallsUsed") is not None:
            tool_calls.append(v["toolCallsUsed"])
        if v.get("passed"):
            verified += 1
        if predicted == "UNCERTAIN":
            escalated_uncertain += 1

        ok = correct_action(kind, report.get("recommended_action"))
        if ok is not None:
            action_hits[kind].append(ok)

        if kind == "planted" and truth in PATTERNS:
            per_pattern[truth].append(predicted == truth)
            confusion[(truth, predicted)] += 1

    def rate(hits: list[bool]) -> dict[str, Any] | None:
        return {"n": len(hits), "correct": round(sum(hits) / len(hits), 3)} if hits else None

    agreement = {p: rate(hits) for p, hits in sorted(per_pattern.items()) if hits}
    matched = sum(len(h) for h in per_pattern.values())
    all_actions = [ok for hits in action_hits.values() for ok in hits]
    return {
        "cases": len(results),
        "starvedCases": n_starved,
        "byKind": dict(kinds),
        # Named agreement, not accuracy: triage hands the agent the engine's own signal
        # codes, so this is largely determined before the model does any work. See the note
        # the table prints under it.
        "typeAgreementPerPattern": agreement,
        "typeAgreement": round(sum(sum(h) for h in per_pattern.values()) / matched, 3) if matched else None,
        # The metric that measures judgement rather than echo: the engine does not tell the
        # agent whether the transaction is actually fraudulent, only that something fired.
        "actionAccuracy": round(sum(all_actions) / len(all_actions), 3) if all_actions else None,
        "actionAccuracyByKind": {k: rate(v) for k, v in sorted(action_hits.items())},
        "verifyPassRate": round(verified / len(results), 3) if results else None,
        "escalatedUncertain": escalated_uncertain,
        "meanToolCalls": round(statistics.mean(tool_calls), 2) if tool_calls else None,
        "maxToolCalls": max(tool_calls) if tool_calls else None,
        "confusion": {f"{t}->{p}": n for (t, p), n in sorted(confusion.items())},
    }


def markdown(summary: dict[str, Any], meta: dict[str, Any]) -> str:
    kinds = summary.get("byKind") or {}
    lines = [
        f"## Agent evals ({meta['model']} via {meta['provider']}, {meta['ranAt']})",
        "",
        f"{summary['cases']} cases investigated: {kinds.get('planted', 0)} planted by the "
        f"generator, {kinds.get('policy', 0)} policy breaches (a hard rule fired), "
        f"{kinds.get('falsePositive', 0)} engine false positives.",
        "",
    ]
    if summary.get("starvedCases"):
        lines += [f"A further {summary['starvedCases']} case(s) are excluded: the provider's "
                  f"free-tier quota ran out mid-run, so the model never answered and the graph "
                  f"escalated them as UNCERTAIN by design. Counting those as wrong answers "
                  f"would report a quota as a quality measurement.", ""]

    lines += [
        "### Did it make the right call?",
        "",
        "The headline metric. The engine tells the agent *that* something fired, never whether "
        "the transaction is genuinely fraudulent, so this measures judgement.",
        "",
        "| case kind | cases | right call |",
        "|---|---|---|",
    ]
    labels = {"planted": "planted fraud (confirm)", "policy": "policy breach (confirm)",
              "falsePositive": "engine false positive (release or escalate)"}
    for kind, s2 in (summary.get("actionAccuracyByKind") or {}).items():
        if s2:
            lines.append(f"| {labels.get(kind, kind)} | {s2['n']} | {s2['correct']:.0%} |")
    lines += [f"| **all** | **{sum((s2 or {}).get('n', 0) for s2 in (summary.get('actionAccuracyByKind') or {}).values())}** "
              f"| **{_pct(summary.get('actionAccuracy'))}** |", ""]

    lines += [
        "### Did its claims hold up?",
        "",
        "| metric | value |",
        "|---|---|",
        f"| reports whose every claim survived the citation check | {_pct(summary['verifyPassRate'])} |",
        f"| mean tool calls per case | {summary['meanToolCalls']} |",
        f"| escalated as UNCERTAIN | {summary['escalatedUncertain']} |",
        "",
        "A report that fails the check twice is published as UNCERTAIN with its unsupported "
        "claims removed, so a low pass rate costs recall rather than producing a confidently "
        "wrong report.",
        "",
        "### Fraud-type agreement with the engine",
        "",
        "| injected pattern | cases | agreement |",
        "|---|---|---|",
    ]
    for pattern, s2 in (summary.get("typeAgreementPerPattern") or {}).items():
        lines.append(f"| {pattern} | {s2['n']} | {s2['correct']:.0%} |")
    lines += [
        f"| **all** | **{sum(s2['n'] for s2 in (summary.get('typeAgreementPerPattern') or {}).values())}** "
        f"| **{_pct(summary.get('typeAgreement'))}** |",
        "",
        "**Read this one with suspicion.** Triage hands the agent the rule codes the engine "
        "fired, and `GEO_IMPOSSIBLE` maps to `GEO` with no reasoning required. A high number "
        "here mostly confirms the agent can read a list, which is why the action table above "
        "is the headline instead. Hiding the codes would be the fix, but it would also make "
        "the agent less useful than a real analyst, who does see what fired.",
    ]
    return "\n".join(lines)


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="score the analyst agent against the generator's ground truth")
    ap.add_argument("--agent-url", default=os.environ.get("FRAUDGRAPH_AGENT_URL", "http://localhost:8000"))
    ap.add_argument("--case-service-url", default=os.environ.get("FRAUDGRAPH_CASE_SERVICE_URL", "http://localhost:8082"))
    ap.add_argument("--bootstrap-servers", default=os.environ.get("FRAUDGRAPH_BOOTSTRAP_SERVERS", "localhost:29092"))
    ap.add_argument("--limit", type=int, default=30, help="cases to investigate")
    ap.add_argument("--hours", type=float, default=6.0, help="how far back to read ground truth")
    ap.add_argument("--sleep", type=float, default=2.0,
                    help="seconds between cases; free tiers are rate limited per minute")
    ap.add_argument("--timeout", type=float, default=300.0, help="per-case timeout")
    ap.add_argument("--out", default="evals/results")
    ap.add_argument("--only-labelled", action="store_true", help="skip cases with no ground truth")
    ap.add_argument("--rules", default=None, metavar="CODE",
                    help="only cases where this rule code fired, filtered by the case API. "
                         "Rings are ~1%% of traffic because only the hop that closes a cycle "
                         "fires, so a random sample never contains one: --rules RING_SUSPECT")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    health = httpx.get(f"{args.agent_url}/health", timeout=10).json()
    if health.get("status") != "UP":
        print(f"agent is not ready: {health}", file=sys.stderr)
        return 1
    log.info("agent: provider=%s model=%s", health.get("provider"), health.get("model"))

    labels = read_labels(args.bootstrap_servers, args.hours)
    log.info("ground truth: %d planted transactions in the last %.0fh", len(labels), args.hours)

    rule = args.rules.strip().upper() if args.rules else None
    overfetch = args.limit * 4 if args.only_labelled else args.limit
    cases = fetch_cases(args.case_service_url, overfetch, rule)
    selected = []
    for c in cases:
        truth = labels.get(c["txnId"])
        if args.only_labelled and truth is None:
            continue
        selected.append({**c, "truth": truth})
        if len(selected) >= args.limit:
            break
    if rule and not selected:
        print(f"no cases where {rule} fired; is that pattern being injected?", file=sys.stderr)
        return 1
    if rule and len(selected) < args.limit:
        log.warning("only %d case(s) where %s fired, asked for %d", len(selected), rule, args.limit)
    log.info("investigating %d cases (%d with ground truth)",
             len(selected), sum(1 for c in selected if c["truth"]))

    results: list[dict[str, Any]] = []
    for i, c in enumerate(selected, 1):
        out = investigate(args.agent_url, c["caseId"], args.timeout)
        if out is None:
            continue
        report = out.get("report") or {}
        results.append({"caseId": c["caseId"], "truth": c["truth"],
                        "firedRules": c.get("firedRules"), "report": report, "notes": out.get("notes")})
        v = report.get("verification") or {}
        log.info("[%d/%d] %s truth=%s predicted=%s verified=%s tools=%s",
                 i, len(selected), c["caseId"][:8], c["truth"], report.get("fraud_type"),
                 v.get("passed"), v.get("toolCallsUsed"))
        if args.sleep and i < len(selected):
            time.sleep(args.sleep)

    summary = score(results)
    meta = {"provider": health.get("provider"), "model": health.get("model"),
            "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"{stamp}.json").write_text(json.dumps({"meta": meta, "summary": summary, "results": results}, indent=2))
    table = markdown(summary, meta)
    (out_dir / f"{stamp}.md").write_text(table)
    (out_dir / "latest.md").write_text(table)
    print()
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
