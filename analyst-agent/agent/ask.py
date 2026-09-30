"""Ask the analyst: a question about one case, answered sentence by sentence with citations.

The same guard as the reports. Every sentence must cite the evidence it rests on, and the
verifier removes any sentence whose citations do not hold before the answer reaches anyone.
Removed sentences are returned alongside the answer with the reason, so the UI can show the
guard working rather than silently tidying the model's output.

Token economy, because this runs on a free tier: the common case is ONE model call. The model
is shown the evidence already collected for the case (the engine's decision, plus the agent
report's evidence when there is one) and either answers or names the tools it needs. Tool
arguments are filled in from the case, never taken from the model, so a question cannot aim a
tool at an account the case does not involve.

The contract, including the response shape the dashboard renders, is docs/showcase-contract.md.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .llm import parse_json_object
from .models import Evidence, Finding, Violation
from .prompts import ASK_FORMAT_REMINDER, ASK_MUST_ANSWER, ASK_SYSTEM, TRIAGE_HYPOTHESES, evidence_block
from .settings import Settings
from .tools import CALLABLE_TOOLS
from .verify import verify_claims, violations_prompt

log = logging.getLogger(__name__)

# Only the most recent turns are resent: each one costs tokens on every later question.
MAX_HISTORY_TURNS = 6
MAX_SENTENCES = 6
MAX_QUESTION_CHARS = 500
# The decision is the document every answer hangs off, and at ~900 characters it sits right
# at the per-entry budget the report graph uses. It is never truncated in practice at this size.
DECISION_PROMPT_CHARS = 2400


class CaseNotFound(Exception):
    pass


class CaseUnavailable(Exception):
    """The case service could not be reached, as opposed to the case not existing."""


@dataclass
class _Draft:
    sentences: list[dict[str, Any]]
    needs: list[str]
    provider_error: bool = False


def parse_draft(raw: str) -> _Draft:
    doc = parse_json_object(raw or "")
    if not isinstance(doc, dict):
        return _Draft([], [])
    needs = []
    for n in doc.get("needs") or []:
        if isinstance(n, str) and n in CALLABLE_TOOLS and n not in needs:
            needs.append(n)
    sentences = []
    for s in (doc.get("sentences") or [])[:MAX_SENTENCES]:
        if not isinstance(s, dict) or not isinstance(s.get("text"), str) or not s["text"].strip():
            continue
        refs = s.get("refs") or []
        refs = [int(r) for r in (refs if isinstance(refs, list) else [refs])
                if isinstance(r, (int, float)) and not isinstance(r, bool) and r >= 0]
        sentences.append({"text": s["text"].strip(), "refs": refs})
    return _Draft(sentences, needs)


def history_view(payload: Any) -> Any:
    """What a question about an account's history is answered from.

    The raw history carries the account's live window counts, which describe the moment the
    question is asked. Asked "is this normal?", the model read them as the account's typical
    rate every time, however the prompt described them, so they are left out here; the
    decision's own features are the counts at decision time. Per-decision latencies and ids
    go too: they are numbers a claim can match by coincidence and mean nothing to the
    question. The evidence panel shows exactly this view, so what the model saw, what the
    verifier checked and what a reader sees are the same thing."""
    if not isinstance(payload, dict) or "profile" not in payload:
        return payload
    profile = payload.get("profile") or {}
    recent = payload.get("recent") or []
    return {
        "userId": payload.get("userId"),
        "amountProfileLifetime": {"transactions": profile.get("n"), "meanAmount": profile.get("mean"),
                                  "stdAmount": profile.get("std")},
        "periodHours": payload.get("hours"),
        "decisionsInPeriod": payload.get("recentTruncatedFrom") or len(recent),
        "latestDecisions": [
            {"verdict": d.get("verdict"), "firedRules": d.get("firedRules") or [],
             "mlScore": round(d["mlScore"], 4) if isinstance(d.get("mlScore"), (int, float)) else None,
             "decidedAt": d.get("decidedAt")}
            for d in recent[:5] if isinstance(d, dict)
        ],
    }


def _shaped(ev: Evidence) -> Evidence:
    if ev.tool == "get_user_history" and ev.ok():
        return Evidence(tool=ev.tool, args=ev.args, payload=history_view(ev.payload))
    return ev


def initial_evidence(case: dict[str, Any]) -> list[Evidence]:
    """[0] is the decision; after it, whatever the report agent already gathered, re-indexed
    from 1 so the answer's citations point into this response and nowhere else."""
    decision = case.get("decisionDoc") or {}
    evidence = [Evidence(tool="decision", args={"txnId": decision.get("txnId") or case.get("txnId")},
                         payload=decision)]
    for entry in (case.get("reportDoc") or {}).get("evidence") or []:
        tool = entry.get("tool")
        if not tool or tool == "get_case":         # the case itself is already evidence [0]
            continue
        args = entry.get("args") or {}
        if "error" in entry:
            evidence.append(Evidence(tool=tool, args=args, error=str(entry["error"])))
        else:
            evidence.append(_shaped(Evidence(tool=tool, args=args, payload=entry.get("payload"))))
    return evidence


def _similar_query(case: dict[str, Any]) -> str:
    summary = (case.get("reportDoc") or {}).get("summary")
    if summary:
        return summary
    fired = (case.get("decisionDoc") or {}).get("firedRules") or case.get("firedRules") or []
    return ". ".join(TRIAGE_HYPOTHESES.get(code, code) for code in fired) or "flagged transaction"


# Questions the decision alone can never answer. Fetching their evidence before the first
# draft saves a model round trip, and stops the model answering them by inference from the
# decision, which it otherwise does: asked whether a burst was normal for the account, it
# will reason from the rule limits rather than ask for the account's history. Visible in
# `steps` like any other tool call. The model can still ask for more with `needs`.
QUESTION_ROUTES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(normal|usual|unusual|typical|typically|history|previous|previously|before|spree|genuine|legit\w*)\b"),
     "get_user_history"),
    (re.compile(r"\b(where did|where does|where is|come from|go to|went|who|counterpart\w*|rings?|chain|layering|"
                r"forward\w*|neighbo\w*|network|cycle)\b"),
     "get_graph_neighborhood"),
    (re.compile(r"\b(similar|precedent\w*|other cases|resolved|how did .* end)\b"),
     "find_similar_cases"),
)


def route_question(question: str) -> list[str]:
    q = question.lower()
    return [tool for pattern, tool in QUESTION_ROUTES if pattern.search(q)]


def run_tool(tools: Any, name: str, case: dict[str, Any]) -> Evidence:
    user_id = (case.get("decisionDoc") or {}).get("userId") or case.get("userId")
    if name == "get_user_history":
        return _shaped(tools.get_user_history(user_id, 24))
    if name == "get_window_counts":
        return tools.get_window_counts(user_id)
    if name == "get_graph_neighborhood":
        return tools.get_graph_neighborhood(user_id, 2)
    if name == "find_similar_cases":
        return tools.find_similar_cases(_similar_query(case), None)
    return Evidence(tool=name, args={}, error="no such tool")    # unreachable: parse_draft filters


def build_prompt(question: str, history: list[dict[str, str]], evidence: list[Evidence],
                 settings: Settings) -> str:
    lines = ["EVIDENCE",
             evidence_block(evidence, settings.max_payload_chars, first_payload_chars=DECISION_PROMPT_CHARS), ""]
    turns = [t for t in history
             if isinstance(t, dict) and t.get("role") in ("user", "assistant") and t.get("content")]
    if turns:
        lines.append("EARLIER IN THIS CONVERSATION")
        lines += [f"{t['role']}: {str(t['content'])[:600]}" for t in turns[-MAX_HISTORY_TURNS:]]
        lines.append("")
    lines += ["QUESTION", question.strip()[:MAX_QUESTION_CHARS]]
    return "\n".join(lines)


def ask_case(case_id: str, question: str, history: list[dict[str, str]] | None,
             settings: Settings, tools: Any, llm: Any) -> dict[str, Any]:
    """Answers one question. Model and tool trouble becomes an empty or partial answer with the
    reason in `steps`, never an exception; an unknown or unreachable case raises."""
    started = time.perf_counter()
    steps: list[dict[str, Any]] = []
    history = history or []

    def step(kind: str, label: str, t0: float, detail: str | None = None) -> None:
        steps.append({"kind": kind, "label": label, "ms": int((time.perf_counter() - t0) * 1000),
                      **({"detail": detail} if detail else {})})

    t0 = time.perf_counter()
    case_ev = tools.get_case(case_id)
    if not case_ev.ok():
        if case_ev.error == "not found":
            raise CaseNotFound(case_id)
        raise CaseUnavailable(case_ev.error or "unknown error")
    case = case_ev.payload or {}
    evidence = initial_evidence(case)
    earlier = len(evidence) - 1
    step("evidence", "Loaded the decision and its signals"
         + (f", plus {earlier} result(s) from the analyst report" if earlier else ""), t0)

    all_violations: list[Violation] = []
    attempts = 0

    def draft(extra: list[str]) -> _Draft:
        nonlocal attempts
        attempts += 1
        t = time.perf_counter()
        messages = [SystemMessage(ASK_SYSTEM), HumanMessage(build_prompt(question, history, evidence, settings))]
        messages += [HumanMessage(x) for x in extra]
        try:
            reply = llm.invoke(messages)
        except Exception as e:  # noqa: BLE001 - a provider failure is an empty answer, not a 500
            log.warning("ask: model call failed for case %s: %s", case_id, e)
            step("draft", "The model could not be reached", t, str(e)[:200])
            return _Draft([], [], provider_error=True)
        d = parse_draft(getattr(reply, "content", "") or "")
        step("draft", "Drafted an answer" if d.sentences
             else "Asked for more evidence" if d.needs
             else "The model's reply was not in the required format", t)
        return d

    budget = settings.ask_max_tools

    def fetch(names: list[str]) -> None:
        nonlocal budget
        for name in names:
            if budget <= 0 or any(e.tool == name and e.ok() for e in evidence):
                continue
            budget -= 1
            t = time.perf_counter()
            ev = run_tool(tools, name, case)
            evidence.append(ev)
            shown = ", ".join(str(v) for k, v in ev.args.items() if k != "summary_text")
            step("tool", f"{name}({shown})", t, ev.error)

    fetch(route_question(question))
    d = draft([])
    if d.needs and not d.sentences:
        fetch(d.needs)
        d = draft([ASK_MUST_ANSWER])

    answer, removed = _check(d.sentences, evidence, all_violations)
    if not answer and not d.provider_error:
        # Nothing usable: every sentence failed the check, or the reply was not parseable.
        # One rewrite, told exactly what was wrong; whatever survives it is the answer.
        extra = ([violations_prompt(all_violations, what="answer")] if removed else [ASK_FORMAT_REMINDER])
        d = draft(extra + [ASK_MUST_ANSWER])
        answer, removed_again = _check(d.sentences, evidence, all_violations)
        removed += [r for r in removed_again if r["text"] not in {x["text"] for x in removed}]

    checked = len(answer) + len(removed)
    steps.append({"kind": "verify", "ms": 0,
                  "label": f"Checked {checked} claim(s) against the evidence"
                           + (f", removed {len(removed)}" if removed else ", all supported" if checked else "")})

    return {
        "caseId": case_id,
        "question": question,
        "answer": answer,
        "removed": removed,
        "evidence": [
            {"index": i, "tool": e.tool, "args": e.args,
             **({"error": e.error} if e.error else {"payload": e.payload})}
            for i, e in enumerate(evidence)
        ],
        "steps": steps,
        # passed: every sentence shown survived the check and there is at least one. The
        # violations are every rejection along the way, including ones a rewrite fixed.
        "verification": {"passed": bool(answer), "attempts": attempts,
                         "violations": [v.model_dump() for v in all_violations]},
        "model": settings.model,
        "latencyMs": int((time.perf_counter() - started) * 1000),
        "mode": "live",
    }


def _check(sentences: list[dict[str, Any]], evidence: list[Evidence],
           seen: list[Violation]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Splits sentences into the verified answer and the removed claims, with reasons."""
    violations = verify_claims([Finding(claim=s["text"], evidence_refs=s["refs"]) for s in sentences], evidence)
    seen += violations
    reasons: dict[int, str] = {}
    for v in violations:
        # The verifier ends a detail with the claim itself, which the model needs on a retry
        # and a reader does not: the removed sentence is shown right next to its reason.
        reasons.setdefault(v.finding_index, _without_claim(v.detail, sentences[v.finding_index]["text"]))
    answer = [{"text": s["text"], "refs": s["refs"], "verified": True}
              for i, s in enumerate(sentences) if i not in reasons]
    removed = [{"text": sentences[i]["text"], "reason": reason} for i, reason in sorted(reasons.items())]
    return answer, removed


def _without_claim(detail: str, claim: str) -> str:
    suffix = f": {claim!r}"
    return detail[: -len(suffix)] if detail.endswith(suffix) else detail


class AnswerCache:
    """The same question about the same case gets the same verified answer without spending
    quota again. Only answers with at least one verified sentence are cached, so a transient
    provider failure is never replayed."""

    def __init__(self, ttl_s: int, size: int = 256, clock=time.monotonic) -> None:
        self._ttl = ttl_s
        self._size = size
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(case_id: str, question: str, history: list[dict[str, str]] | None) -> str:
        norm = " ".join(question.lower().split()).rstrip("?")
        turns = json.dumps((history or [])[-MAX_HISTORY_TURNS:], sort_keys=True)
        return hashlib.sha256(f"{case_id}|{norm}|{turns}".encode()).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        if self._ttl <= 0:
            return None
        with self._lock:
            hit = self._items.get(key)
            if hit is None:
                return None
            if self._clock() - hit[0] > self._ttl:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return hit[1]

    def put(self, key: str, value: dict[str, Any]) -> None:
        if self._ttl <= 0 or not value.get("answer"):
            return
        with self._lock:
            self._items[key] = (self._clock(), value)
            self._items.move_to_end(key)
            while len(self._items) > self._size:
                self._items.popitem(last=False)
