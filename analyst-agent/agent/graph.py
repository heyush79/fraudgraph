"""The investigation graph (LLD §6.1).

    triage -> investigate ⟲ (bounded, <= max_tool_calls) -> similar_cases
           -> draft_report -> verify -> finalize
                                 └─(violations, once)─> investigate

`triage` is deterministic rather than a model call: the fired rules already say what the
engine suspected, so spending a rate-limited request to restate them would be waste. The
model's judgement is needed for investigating and for writing, not for reading a list.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from .models import AgentState, Evidence, FraudType, RecommendedAction, Report, Violation
from .prompts import DRAFT_SYSTEM, INVESTIGATE_SYSTEM, TRIAGE_HYPOTHESES, evidence_block
from .settings import Settings
from .tools import CALLABLE_TOOLS, TOOL_SCHEMAS, Tools
from .verify import verify, violations_prompt

log = logging.getLogger(__name__)


def build_graph(settings: Settings, tools: Tools, llm: Any):
    bound = llm.bind_tools(TOOL_SCHEMAS)

    # -- triage ---------------------------------------------------------------------

    def triage(state: AgentState) -> dict:
        case_evidence = tools.get_case(state["case_id"])
        case = case_evidence.payload if case_evidence.ok() else {}
        decision = (case or {}).get("decisionDoc") or {}
        fired = decision.get("firedRules") or []
        hypotheses = [TRIAGE_HYPOTHESES[code] for code in fired if code in TRIAGE_HYPOTHESES]
        if not hypotheses:
            hypotheses = ["No rule fired; the model score alone drove this verdict"]

        opening = (
            f"Case {state['case_id']}.\n"
            f"Verdict {decision.get('verdict')} in mode {decision.get('mode')}, "
            f"model score {decision.get('mlScore')}.\n"
            f"Account {decision.get('userId')}, merchant {decision.get('merchantId')} "
            f"(category {decision.get('merchantCategory')}), channel "
            f"{(decision.get('features') or {}).get('channel')}.\n"
            f"Rules that fired: {fired or 'none'}.\n"
            f"Working hypotheses: {'; '.join(hypotheses)}.\n"
            f"The full decision, including each signal's evidence, is evidence [0]."
        )
        return {
            "case": case or {},
            "evidence": [case_evidence],
            "hypotheses": hypotheses,
            "tool_calls_used": 0,
            "verify_attempts": 0,
            "messages": [
                SystemMessage(INVESTIGATE_SYSTEM.format(max_tool_calls=settings.max_tool_calls)),
                HumanMessage(opening),
            ],
            "notes": [f"triage: fired={fired}"],
        }

    # -- investigate ----------------------------------------------------------------

    def investigate(state: AgentState) -> dict:
        used = state.get("tool_calls_used", 0)
        remaining = settings.max_tool_calls - used
        messages = list(state.get("messages", []))
        if remaining <= 0:
            return {"messages": [HumanMessage(
                "You have used your entire tool budget. Work with the evidence you have.")],
                "notes": ["investigate: budget exhausted"]}

        try:
            reply: AIMessage = bound.invoke(messages)
        except Exception as e:  # noqa: BLE001 - a provider failure ends the loop, not the run
            log.warning("investigate turn failed: %s", e)
            return {"notes": [f"investigate: model call failed ({e})"],
                    "tool_calls_used": settings.max_tool_calls}

        calls = list(getattr(reply, "tool_calls", None) or [])[:remaining]
        if not calls:
            return {"messages": [reply], "notes": ["investigate: no further tools requested"]}

        new_evidence: list[Evidence] = []
        tool_messages: list[ToolMessage] = []
        for call in calls:
            name, args = call.get("name"), dict(call.get("args") or {})
            if name not in CALLABLE_TOOLS:
                ev = Evidence(tool=str(name), args=args, error="no such tool")
            else:
                try:
                    ev = getattr(tools, name)(**args)
                except TypeError as e:
                    ev = Evidence(tool=name, args=args, error=f"bad arguments: {e}")
            new_evidence.append(ev)
            # The index the model must cite is its position in the accumulated list.
            index = len(state.get("evidence", [])) + len(new_evidence) - 1
            body = {"evidence_index": index,
                    **({"error": ev.error} if ev.error else {"result": ev.payload})}
            tool_messages.append(ToolMessage(
                content=json.dumps(body, default=str)[: settings.max_payload_chars],
                tool_call_id=call.get("id", name)))

        return {
            "messages": [reply, *tool_messages],
            "evidence": new_evidence,
            "tool_calls_used": used + len(calls),
            "notes": [f"investigate: called {[c.get('name') for c in calls]}"],
        }

    def after_investigate(state: AgentState) -> str:
        if state.get("tool_calls_used", 0) >= settings.max_tool_calls:
            return "similar_cases"
        last = (state.get("messages") or [None])[-1]
        # a ToolMessage last means the model is mid-loop and should get another turn
        return "investigate" if isinstance(last, ToolMessage) else "similar_cases"

    # -- similar cases --------------------------------------------------------------

    def similar_cases(state: AgentState) -> dict:
        decision = (state.get("case") or {}).get("decisionDoc") or {}
        query = (f"{decision.get('verdict')} {decision.get('firedRules')} "
                 f"{'; '.join(state.get('hypotheses') or [])}")
        ev = tools.find_similar_cases(query, settings.similar_k)
        found = ev.payload if ev.ok() else []
        return {"evidence": [ev], "similar": found or [],
                "notes": [f"similar_cases: {len(found or [])} match(es)"]}

    # -- draft ----------------------------------------------------------------------

    def draft_report(state: AgentState) -> dict:
        evidence = state.get("evidence", [])
        prompt = DRAFT_SYSTEM.format(
            evidence_block=evidence_block(evidence, settings.max_payload_chars))
        # The investigate transcript is deliberately NOT resent. Everything of substance in it
        # is the tool results, which the evidence block already carries verbatim and numbered;
        # resending the model's own prose about them doubles the drafting cost for nothing.
        # It does cost the model its own earlier reasoning, which is the trade being made.
        messages = [SystemMessage(prompt), HumanMessage(
            f"Case {state['case_id']}. Working hypotheses from triage: "
            f"{'; '.join(state.get('hypotheses') or []) or 'none'}. "
            f"Write the report now.")]
        violations = state.get("violations") or []
        if violations:
            messages.append(HumanMessage(violations_prompt(violations)))

        from .llm import parse_json_object
        try:
            reply = llm.invoke(messages)
            raw = parse_json_object(getattr(reply, "content", "") or "")
        except Exception as e:  # noqa: BLE001
            log.warning("draft failed: %s", e)
            raw = None

        if raw is None:
            return {"report": None, "notes": ["draft_report: no parseable JSON returned"]}
        try:
            report = Report.model_validate(raw)
        except Exception as e:  # noqa: BLE001
            return {"report": None, "notes": [f"draft_report: schema rejected the draft ({e})"]}
        return {"report": report.model_dump(mode="json"), "notes": ["draft_report: drafted"]}

    # -- verify ---------------------------------------------------------------------

    def verify_node(state: AgentState) -> dict:
        attempts = state.get("verify_attempts", 0) + 1
        raw = state.get("report")
        if raw is None:
            v = [Violation(finding_index=-1, kind="no_refs", detail="no report was produced")]
            return {"violations": v, "all_violations": v, "verify_attempts": attempts,
                    "notes": [f"verify: attempt {attempts}, nothing to check"]}
        report = Report.model_validate(raw)
        violations = verify(report, state.get("evidence", []))
        return {"violations": violations, "all_violations": violations, "verify_attempts": attempts,
                "notes": [f"verify: attempt {attempts}, {len(violations)} violation(s)"]}

    def after_verify(state: AgentState) -> str:
        if not state.get("violations"):
            return "finalize"
        if state.get("verify_attempts", 0) < settings.max_verify_attempts:
            return "investigate"     # LLD §6.2: one retry through investigate, then escalate
        return "finalize"

    # -- finalize -------------------------------------------------------------------

    def finalize(state: AgentState) -> dict:
        violations = state.get("violations") or []
        report = state.get("report")
        notes: list[str] = []

        if violations or report is None:
            # Escalate honestly rather than publish a report whose citations do not hold.
            kept = []
            if report is not None:
                bad = {v.finding_index for v in violations}
                kept = [f for i, f in enumerate(report.get("findings") or []) if i not in bad]
            report = {
                "summary": ((report or {}).get("summary")
                            or "The agent could not produce a report whose claims are all supported."),
                "fraud_type": FraudType.UNCERTAIN.value,
                "confidence": 0.0,
                "findings": kept,
                "recommended_action": RecommendedAction.ESCALATE.value,
            }
            notes.append(f"finalize: escalated as UNCERTAIN after {len(violations)} unresolved violation(s)")
        else:
            notes.append("finalize: report verified")

        # The report carries the evidence it cites. Without it `evidence_refs` point into a
        # list that only existed inside this process, so a human could not check a single
        # citation, which would make the whole citation discipline unfalsifiable from outside.
        report["evidence"] = [
            {"index": i, "tool": e.tool, "args": e.args,
             **({"error": e.error} if e.error else {"payload": e.payload})}
            for i, e in enumerate(state.get("evidence", []))
        ]
        seen, history = set(), []
        for v in state.get("all_violations") or []:
            key = (v.finding_index, v.kind, v.detail)
            if key not in seen:
                seen.add(key)
                history.append(v.model_dump())
        report["verification"] = {
            "passed": not violations,
            "attempts": state.get("verify_attempts", 0),
            "violations": history,
            "toolCallsUsed": state.get("tool_calls_used", 0),
            "evidenceCount": len(state.get("evidence", [])),
        }
        attached = tools.attach_report(state["case_id"], report)
        notes.append(f"finalize: report {'attached' if attached else 'NOT attached'}")
        return {"report": report, "notes": notes}

    g = StateGraph(AgentState)
    g.add_node("triage", triage)
    g.add_node("investigate", investigate)
    g.add_node("similar_cases", similar_cases)
    g.add_node("draft_report", draft_report)
    g.add_node("verify", verify_node)
    g.add_node("finalize", finalize)

    g.add_edge(START, "triage")
    g.add_edge("triage", "investigate")
    g.add_conditional_edges("investigate", after_investigate,
                            {"investigate": "investigate", "similar_cases": "similar_cases"})
    g.add_edge("similar_cases", "draft_report")
    g.add_edge("draft_report", "verify")
    g.add_conditional_edges("verify", after_verify,
                            {"investigate": "investigate", "finalize": "finalize"})
    g.add_edge("finalize", END)
    # recursion_limit guards against a cycle the conditional edges failed to break
    return g.compile()
