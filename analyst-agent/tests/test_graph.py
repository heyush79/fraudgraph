"""End-to-end graph runs with a scripted model: no API key, fully deterministic."""
from __future__ import annotations

from dataclasses import replace

from agent.graph import build_graph

from .conftest import CASE, STOP, FakeTools, ScriptedLLM

GOOD_REPORT = {
    "summary": "The account made 18 card payments in 60 seconds at a gift-card merchant, "
               "far above the limit of 8, consistent with automated card testing.",
    "fraud_type": "VELOCITY", "confidence": 0.86,
    "findings": [
        {"claim": "18 transactions were made in 60 seconds against a limit of 8.", "evidence_refs": [0]},
        {"claim": "The one-hour count reached 37 transactions.", "evidence_refs": [1]},
    ],
    "recommended_action": "CONFIRM_BLOCK",
}

FABRICATED_REPORT = {
    "summary": "Clear card testing.",
    "fraud_type": "VELOCITY", "confidence": 0.99,
    "findings": [{"claim": "The account made 250 transactions in 60 seconds.", "evidence_refs": [0]}],
    "recommended_action": "CONFIRM_BLOCK",
}


def run(settings, turns, tools=None):
    tools = tools or FakeTools()
    llm = ScriptedLLM(turns)
    final = build_graph(settings, tools, llm).invoke({"case_id": CASE["caseId"]}, {"recursion_limit": 50})
    return final, tools, llm


def test_a_verified_report_is_attached(settings):
    final, tools, _ = run(settings, [
        {"tools": [("get_window_counts", {"user_id": "u_10903"})]},
        STOP,
        GOOD_REPORT,
    ])
    report = final["report"]
    assert report["fraud_type"] == "VELOCITY"
    assert report["verification"]["passed"] is True
    assert report["verification"]["attempts"] == 1
    assert report["verification"]["violations"] == []
    assert tools.attached == report               # written back to the case service
    assert [c[0] for c in tools.calls][:2] == ["get_case", "get_window_counts"]
    # every citation resolves against evidence carried in the report itself
    carried = report["evidence"]
    assert [e["index"] for e in carried] == list(range(len(carried)))
    assert carried[1]["tool"] == "get_window_counts"
    for finding in report["findings"]:
        for ref in finding["evidence_refs"]:
            assert carried[ref]["index"] == ref
            assert "payload" in carried[ref]


def test_a_fabricated_number_forces_a_retry_then_escalates(settings):
    final, tools, llm = run(settings, [
        {"tools": [("get_window_counts", {"user_id": "u_10903"})]},
        STOP, FABRICATED_REPORT,       # first draft fabricates a number
        STOP, FABRICATED_REPORT,       # the retry does not fix it
    ])
    report = final["report"]
    assert report["fraud_type"] == "UNCERTAIN"
    assert report["recommended_action"] == "ESCALATE"
    assert report["confidence"] == 0.0
    assert report["findings"] == []               # the unsupported claim is dropped, not published
    assert report["verification"]["passed"] is False
    assert report["verification"]["attempts"] == 2
    # the reason the first draft was rejected survives into the escalated report
    assert any(v["kind"] == "uncited_number" for v in report["verification"]["violations"])
    assert any("250" in v["detail"] for v in report["verification"]["violations"])
    assert tools.attached is not None             # the case still gets the honest answer


def test_the_retry_can_succeed(settings):
    final, _, _ = run(settings, [
        {"tools": [("get_window_counts", {"user_id": "u_10903"})]},
        STOP, FABRICATED_REPORT,                                      # draft 1 fails
        {"tools": [("get_user_history", {"user_id": "u_10903"})]},    # retry gathers more
        STOP, GOOD_REPORT,                                            # draft 2 is citable
    ])
    report = final["report"]
    assert report["verification"]["passed"] is True
    assert report["verification"]["attempts"] == 2
    assert report["fraud_type"] == "VELOCITY"


def test_the_tool_budget_is_a_hard_stop(settings):
    tight = replace(settings, max_tool_calls=3)
    # the model asks for a tool on every turn and would never stop on its own
    final, tools, _ = run(tight, [{"tools": [("get_window_counts", {"user_id": "u_10903"})]}] * 10
                          + [STOP, GOOD_REPORT])
    assert final["tool_calls_used"] == 3
    model_calls = [c for c in tools.calls if c[0] in {"get_window_counts", "get_user_history"}]
    assert len(model_calls) == 3


def test_a_failed_tool_is_recorded_and_cannot_be_cited(settings):
    tools = FakeTools(get_window_counts=RuntimeError("503 from the engine"))
    cite_the_failure = {
        "summary": "Counts were elevated.", "fraud_type": "VELOCITY", "confidence": 0.7,
        "findings": [{"claim": "The one-minute count was 18.", "evidence_refs": [1]}],
        "recommended_action": "CONFIRM_BLOCK",
    }
    final, tools, _ = run(settings, [
        {"tools": [("get_window_counts", {"user_id": "u_10903"})]},
        STOP, cite_the_failure,
        STOP, cite_the_failure,
    ], tools=tools)
    kinds = [v["kind"] for v in final["report"]["verification"]["violations"]]
    assert "failed_tool_ref" in kinds
    # the failed call is still carried, marked, so a reader can see what was attempted
    failed = [e for e in final["report"]["evidence"] if "error" in e]
    assert failed and failed[0]["tool"] == "get_window_counts"
    assert final["report"]["fraud_type"] == "UNCERTAIN"


def test_unparseable_output_escalates_rather_than_crashing(settings):
    final, _, _ = run(settings, [
        {"tools": [("get_window_counts", {"user_id": "u_10903"})]},
        STOP, "I think this is fraud but here is no JSON at all.",
        STOP, "still no JSON",
    ])
    assert final["report"]["fraud_type"] == "UNCERTAIN"
    assert final["report"]["verification"]["passed"] is False


def test_a_provider_failure_while_drafting_is_named_as_such(settings):
    """A 429 during drafting and a model writing prose are different failures. The eval
    harness reads these notes to decide whether a case measured the agent or the quota."""
    final, _, _ = run(settings, [
        {"tools": [("get_window_counts", {"user_id": "u_10903"})]},
        STOP, RuntimeError("Error code: 429 - rate_limit_exceeded"),
        STOP, RuntimeError("Error code: 429 - rate_limit_exceeded"),
    ])
    notes = " | ".join(final["notes"])
    assert "draft_report: model call failed" in notes
    assert "no parseable JSON" not in notes
    assert final["report"]["fraud_type"] == "UNCERTAIN"


def test_prose_instead_of_json_is_reported_differently(settings):
    final, _, _ = run(settings, [
        {"tools": [("get_window_counts", {"user_id": "u_10903"})]},
        STOP, "I believe this is card testing.",
        STOP, "Still prose, still no JSON.",
    ])
    notes = " | ".join(final["notes"])
    assert "no parseable JSON" in notes
    assert "model call failed" not in notes


def test_a_model_outage_mid_investigation_still_produces_a_report(settings):
    final, _, _ = run(settings, [RuntimeError("rate limited"), GOOD_REPORT, STOP, GOOD_REPORT])
    # the investigate turn failed, so only the case itself is evidence; finding #1 cites
    # evidence 1 which does not exist, so this must escalate rather than publish
    assert final["report"]["fraud_type"] == "UNCERTAIN"
    assert any("model call failed" in n for n in final["notes"])


def test_triage_derives_hypotheses_from_the_fired_rules(settings):
    final, _, _ = run(settings, [STOP, GOOD_REPORT])
    assert any("card testing" in h for h in final["hypotheses"])
    assert final["evidence"][0].tool == "get_case"
    assert any("fired=['VELOCITY_1M', 'VELOCITY_5M']" in n for n in final["notes"])


def test_an_unknown_tool_name_is_rejected_not_executed(settings):
    final, tools, _ = run(settings, [
        {"tools": [("drop_database", {"x": 1})]},
        STOP, GOOD_REPORT,
    ])
    bad = [e for e in final["evidence"] if e.tool == "drop_database"]
    assert bad and bad[0].error == "no such tool"
    assert not any(c[0] == "drop_database" for c in tools.calls)


def test_report_invariants_the_dashboard_relies_on(settings):
    """Pinned because the dashboard resolves citations against these guarantees."""
    final, _, _ = run(settings, [
        {"tools": [("get_window_counts", {"user_id": "u_10903"}),
                   ("get_user_history", {"user_id": "u_10903"})]},
        STOP, GOOD_REPORT,
    ])
    report = final["report"]
    evidence = report["evidence"]
    # the array is dense and ordered, so index and array position always agree
    assert [e["index"] for e in evidence] == list(range(len(evidence)))
    # and the count in the verification summary is the same list, never a different total
    assert report["verification"]["evidenceCount"] == len(evidence)
    # every entry carries exactly one of payload or error
    for e in evidence:
        assert ("payload" in e) != ("error" in e)


def test_a_report_that_passed_on_the_retry_keeps_the_corrections_it_needed(settings):
    """passed=true with a non-empty violations list is intentional, not a contradiction: the
    list is the union across attempts, so it records what the first draft got wrong."""
    final, _, _ = run(settings, [
        {"tools": [("get_window_counts", {"user_id": "u_10903"})]},
        STOP, FABRICATED_REPORT,                                      # draft 1 fabricates
        {"tools": [("get_user_history", {"user_id": "u_10903"})]},
        STOP, GOOD_REPORT,                                            # draft 2 is citable
    ])
    v = final["report"]["verification"]
    assert v["passed"] is True
    assert v["attempts"] == 2
    assert any(x["kind"] == "uncited_number" for x in v["violations"])
    assert final["report"]["fraud_type"] == "VELOCITY"    # the good report is what ships
