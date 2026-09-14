"""The scoring logic, with no stack and no model."""
from __future__ import annotations

from evals.run import classify, correct_action, markdown, score, starved


def result(truth, predicted, *, passed=True, tools=3, action="CONFIRM_BLOCK", fired=None, notes=None):
    return {"caseId": "c", "truth": truth, "firedRules": fired if fired is not None else ["VELOCITY_1M"],
            "notes": notes or ["investigate: called ['x']", "draft_report: drafted"],
            "report": {"fraud_type": predicted, "recommended_action": action,
                       "verification": {"passed": passed, "toolCallsUsed": tools}}}


# -- classification ----------------------------------------------------------

def test_a_hard_rule_case_is_a_policy_breach_not_a_false_positive():
    """Confirming a sanctioned-merchant block is correct even with no ground-truth label.
    The first version of this harness scored it as 'should have declined' and marked the
    agent wrong for being right."""
    assert classify(result(None, "MIXED", fired=["HARD_BLOCK_MERCHANT"])) == "policy"
    assert classify(result(None, "GEO", fired=["GEO_IMPOSSIBLE"])) == "falsePositive"
    assert classify(result("VELOCITY", "VELOCITY")) == "planted"
    assert classify(result(None, "X", fired=["AMOUNT_CAP"])) == "policy"


def test_the_right_call_depends_on_the_kind():
    assert correct_action("planted", "CONFIRM_BLOCK") is True
    assert correct_action("planted", "RELEASE") is False
    assert correct_action("policy", "CONFIRM_BLOCK") is True
    assert correct_action("falsePositive", "RELEASE") is True
    assert correct_action("falsePositive", "ESCALATE") is True
    assert correct_action("falsePositive", "CONFIRM_BLOCK") is False
    assert correct_action("planted", None) is None


# -- the headline metric -----------------------------------------------------

def test_action_accuracy_is_reported_per_kind_and_overall():
    s = score([
        result("VELOCITY", "VELOCITY", action="CONFIRM_BLOCK"),
        result("GEO", "GEO", action="RELEASE"),                                    # miss
        result(None, "MIXED", action="CONFIRM_BLOCK", fired=["HARD_BLOCK_MERCHANT"]),
        result(None, "GEO", action="CONFIRM_BLOCK", fired=["GEO_IMPOSSIBLE"]),     # miss
    ])
    assert s["byKind"] == {"planted": 2, "policy": 1, "falsePositive": 1}
    assert s["actionAccuracyByKind"]["planted"] == {"n": 2, "correct": 0.5}
    assert s["actionAccuracyByKind"]["policy"] == {"n": 1, "correct": 1.0}
    assert s["actionAccuracyByKind"]["falsePositive"] == {"n": 1, "correct": 0.0}
    assert s["actionAccuracy"] == 0.5


def test_type_agreement_is_reported_separately_from_judgement():
    s = score([result("VELOCITY", "VELOCITY"), result("GEO", "MIXED")])
    assert s["typeAgreementPerPattern"]["VELOCITY"] == {"n": 1, "correct": 1.0}
    assert s["typeAgreementPerPattern"]["GEO"] == {"n": 1, "correct": 0.0}
    assert s["typeAgreement"] == 0.5
    assert s["confusion"]["GEO->MIXED"] == 1


def test_verify_pass_rate_and_tool_calls():
    s = score([result("GEO", "GEO", passed=True, tools=2),
               result("GEO", "GEO", passed=False, tools=4),
               result("GEO", "UNCERTAIN", passed=False, tools=4)])
    assert s["verifyPassRate"] == 0.333
    assert s["meanToolCalls"] == 3.33
    assert s["maxToolCalls"] == 4
    assert s["escalatedUncertain"] == 1


# -- provider starvation is not a quality measurement ------------------------

def test_starved_cases_are_excluded_from_quality_metrics():
    quota_notes = ["investigate: model call failed (Error code: 429 ...)",
                   "draft_report: no parseable JSON returned"]
    ran = result("VELOCITY", "VELOCITY")
    quota = result("GEO", "UNCERTAIN", passed=False, tools=4, action="ESCALATE", notes=quota_notes)
    assert starved(quota) is True and starved(ran) is False
    s = score([ran, quota])
    assert s["cases"] == 1 and s["starvedCases"] == 1
    assert s["actionAccuracy"] == 1.0
    assert s["typeAgreement"] == 1.0


def test_a_genuine_verification_failure_is_still_counted_against_the_agent():
    bad = result("VELOCITY", "UNCERTAIN", passed=False, tools=4, action="ESCALATE",
                 notes=["investigate: called ['x']", "draft_report: drafted", "verify: attempt 2, 1 violation(s)"])
    assert starved(bad) is False
    s = score([bad])
    assert s["starvedCases"] == 0
    assert s["verifyPassRate"] == 0.0
    assert s["actionAccuracyByKind"]["planted"] == {"n": 1, "correct": 0.0}


def test_empty_run_does_not_divide_by_zero():
    s = score([])
    assert s["cases"] == 0
    assert s["actionAccuracy"] is None and s["typeAgreement"] is None and s["meanToolCalls"] is None


# -- the table ---------------------------------------------------------------

def test_the_table_leads_with_judgement_and_disclaims_type_agreement():
    s = score([result("VELOCITY", "VELOCITY"),
               result(None, "MIXED", fired=["HARD_BLOCK_MERCHANT"])])
    table = markdown(s, {"model": "gpt-oss-120b", "provider": "groq", "ranAt": "now"})
    assert table.index("Did it make the right call?") < table.index("Fraud-type agreement")
    assert "Read this one with suspicion" in table
    assert "policy breach (confirm)" in table
    assert "gpt-oss-120b via groq" in table


def test_the_table_says_when_a_run_was_starved():
    quota = result("GEO", "UNCERTAIN", passed=False, notes=["investigate: model call failed (429)"])
    table = markdown(score([result("GEO", "GEO"), quota]), {"model": "m", "provider": "groq", "ranAt": "now"})
    assert "quota ran out mid-run" in table
    assert "1 case(s) are excluded" in table


def test_indexed_summary_carries_narrative_and_mechanism():
    from agent.indexer import summary_text
    case = {"firedRules": ["RING_SUSPECT"],
            "reportDoc": {"summary": "Money returned to the sender through four accounts.",
                          "fraud_type": "RING"}}
    text = summary_text(case)
    assert "four accounts" in text and "RING_SUSPECT" in text and "type: RING" in text
    assert summary_text({"firedRules": [], "reportDoc": None}) == "type: UNKNOWN"
