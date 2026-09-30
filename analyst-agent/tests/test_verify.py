"""The verify node is the project's differentiator, so it gets the most tests."""
from __future__ import annotations

import pytest

from agent.models import Evidence, Finding, FraudType, RecommendedAction, Report
from agent.verify import extract_numbers, flatten_numbers, verify, verify_claims, violations_prompt

VELOCITY_EVIDENCE = Evidence(
    tool="get_window_counts", args={"user_id": "u_10903"},
    payload={"cnt1m": 18, "sum1m": 4353.64, "cnt5m": 24, "sum5m": 8156.11, "cnt1h": 37, "sum1h": 25423.32},
)
GEO_EVIDENCE = Evidence(
    tool="get_user_history", args={"user_id": "u_19563", "hours": 24},
    payload={"recent": [{"verdict": "REVIEW", "firedRules": ["GEO_IMPOSSIBLE"],
                         "decidedAt": "2026-09-14T05:49:47.478555Z"}],
             "profile": {"n": 10, "mean": 2486.48, "std": 2115.01}},
)
RING_EVIDENCE = Evidence(
    tool="get_graph_neighborhood", args={"user_id": "u_17818", "depth": 2},
    payload={"nodes": [{"id": "u_17818", "degree": 2}], "edges": [],
             "cycles": [["u_17818", "u_20190", "u_10479", "u_10214", "u_17175", "u_17818"]],
             "componentSize": 10},
)
FAILED_EVIDENCE = Evidence(tool="get_window_counts", args={"user_id": "u_1"}, error="503 from the engine")


def report(claim: str, refs: list[int], **kw) -> Report:
    return Report(summary="s", fraud_type=kw.get("fraud_type", FraudType.VELOCITY), confidence=0.8,
                  findings=[{"claim": claim, "evidence_refs": refs}],
                  recommended_action=kw.get("action", RecommendedAction.CONFIRM_BLOCK))


# -- the happy path ---------------------------------------------------------

# what the engine actually puts on a decision's velocity signal
SIGNAL_EVIDENCE = Evidence(
    tool="get_case", args={"case_id": "c1"},
    payload={"signals": [{"code": "VELOCITY_1M", "severity": 1.0,
                          "evidence": {"count": 18, "limit": 8, "windowSecs": 60, "sum": 4353.64}}]},
)


def test_a_claim_backed_by_its_evidence_passes():
    r = report("The account made 18 transactions in 60 seconds, against a limit of 8.", [0])
    assert verify(r, [SIGNAL_EVIDENCE]) == []


def test_quoting_a_limit_the_cited_evidence_never_mentions_is_caught():
    """The window counts carry no limit, so the limit has to be cited from the signal."""
    r = report("The account made 18 transactions in one minute, against a limit of 8.", [0])
    v = verify(r, [VELOCITY_EVIDENCE])
    assert [x.kind for x in v] == ["uncited_number"]
    assert "quotes 8" in v[0].detail


def test_counting_the_members_of_a_cited_collection_is_supported():
    r = report("Funds moved in a closed loop through 5 distinct accounts, 6 hops in all.",
               [0], fraud_type=FraudType.RING)
    assert verify(r, [RING_EVIDENCE]) == []


def test_rounding_is_allowed():
    ev = [Evidence(tool="t", payload={"speedKmh": 13499.34, "distanceKm": 1151.27})]
    assert verify(report("1,151 km apart implying 13,499 km/h.", [0]), ev) == []
    assert verify(report("About 13,500 km/h over 1151 km.", [0]), ev) == []


def test_numbers_inside_strings_in_the_payload_count():
    ev = [Evidence(tool="t", payload={"note": "cnt1m was 18 at 2026-09-14T05:49:47Z"})]
    assert verify(report("There were 18 transactions.", [0]), ev) == []


def test_a_cycle_of_user_ids_supports_a_claim_about_those_accounts():
    r = report("Funds moved in a closed loop through u_17818, u_20190, u_10479, u_10214 and u_17175.",
               [0], fraud_type=FraudType.RING)
    assert verify(r, [RING_EVIDENCE]) == []


# -- the guard firing -------------------------------------------------------

def test_a_fabricated_number_is_caught():
    r = report("The account made 23 transactions in one minute.", [0])
    v = verify(r, [VELOCITY_EVIDENCE])
    assert len(v) == 1
    assert v[0].kind == "uncited_number"
    assert "23" in v[0].detail


def test_a_claim_with_no_citation_is_caught():
    v = verify(report("This is obviously a laundering ring.", []), [VELOCITY_EVIDENCE])
    assert [x.kind for x in v] == ["no_refs"]


def test_an_out_of_range_citation_is_caught():
    v = verify(report("The account made 18 transactions in one minute.", [0, 7]), [VELOCITY_EVIDENCE])
    assert [x.kind for x in v] == ["bad_ref"]
    assert "indexed 0..0" in v[0].detail


def test_citing_a_failed_tool_call_is_caught():
    v = verify(report("Window counts were elevated at 18 per minute.", [0]), [FAILED_EVIDENCE])
    assert [x.kind for x in v] == ["failed_tool_ref"]


def test_a_number_present_in_other_evidence_but_not_the_cited_evidence_is_caught():
    r = report("The component holds 10 accounts.", [0])
    v = verify(r, [VELOCITY_EVIDENCE, RING_EVIDENCE])   # 10 is in evidence 1, cited 0
    assert [x.kind for x in v] == ["uncited_number"]
    assert verify(report("The component holds 10 accounts.", [1]), [VELOCITY_EVIDENCE, RING_EVIDENCE]) == []


def test_every_bad_finding_is_reported_not_just_the_first():
    r = Report(summary="s", fraud_type=FraudType.MIXED, confidence=0.5,
               findings=[{"claim": "99 transactions", "evidence_refs": [0]},
                         {"claim": "no support here", "evidence_refs": []},
                         {"claim": "18 transactions", "evidence_refs": [0]}],
               recommended_action=RecommendedAction.ESCALATE)
    v = verify(r, [VELOCITY_EVIDENCE])
    assert [x.finding_index for x in v] == [0, 1]
    assert [x.kind for x in v] == ["uncited_number", "no_refs"]


# -- the extractors themselves ---------------------------------------------

def test_number_extraction_handles_separators_and_ignores_timestamps():
    assert extract_numbers("18 transactions in 60 seconds") == [18.0, 60.0]
    assert extract_numbers("1,151 km at 13,499.5 km/h") == [1151.0, 13499.5]
    assert extract_numbers("decided at 2026-09-14T05:49:47.478555Z") == []
    assert extract_numbers("score -3.8 and 0.91") == [-3.8, 0.91]
    assert extract_numbers("no digits here") == []


def test_flatten_walks_nested_structures():
    nums = flatten_numbers({"a": [1, {"b": 2.5}], "c": "seen 300 times", "d": None, "e": True})
    assert {1.0, 2.5, 300.0} <= nums
    assert 0.0 not in nums and 1.0 in nums   # booleans are not numbers here
    assert flatten_numbers(None) == set()


def test_small_integers_are_not_required_to_be_cited():
    # "one of the 2 accounts" is English, not a quantity worth policing
    assert verify(report("Two accounts were involved, so 2 hops occurred.", [0]), [VELOCITY_EVIDENCE]) == []


def test_a_report_with_no_findings_passes_but_says_nothing():
    r = Report(summary="nothing conclusive", fraud_type=FraudType.UNCERTAIN, confidence=0.1,
               findings=[], recommended_action=RecommendedAction.ESCALATE)
    assert verify(r, [VELOCITY_EVIDENCE]) == []


def test_the_retry_prompt_names_each_problem():
    v = verify(report("The account made 23 transactions.", [0]), [VELOCITY_EVIDENCE])
    prompt = violations_prompt(v)
    assert "uncited_number" in prompt and "23" in prompt
    assert "try harder" not in prompt.lower()


def test_negative_refs_are_rejected_by_the_schema():
    with pytest.raises(ValueError, match="non-negative"):
        report("x", [-1])



# -- percentages and claim-level checking (the chat answers use both) ----------

def test_a_percentage_can_cite_a_ratio():
    ev = [Evidence(tool="t", payload={"ratio": 0.961, "chainDepth": 2})]
    assert verify(report("It forwarded 96% of what it received.", [0]), ev) == []
    assert verify(report("It forwarded 96.1% of what it received.", [0]), ev) == []


def test_a_percentage_that_matches_nothing_is_still_caught():
    ev = [Evidence(tool="t", payload={"ratio": 0.961})]
    v = verify(report("It forwarded 50% of what it received.", [0]), ev)
    assert [x.kind for x in v] == ["uncited_number"]
    assert "50%" in v[0].detail


def test_a_bare_number_does_not_get_the_percent_allowance():
    """96 with no % sign must not be excused by a ratio of 0.96."""
    ev = [Evidence(tool="t", payload={"ratio": 0.96})]
    assert [x.kind for x in verify(report("There were 96 transfers.", [0]), ev)] == ["uncited_number"]


def test_verify_claims_checks_sentences_one_by_one():
    from agent.models import Finding
    from agent.verify import verify_claims
    claims = [Finding(claim="18 transactions in 60 seconds.", evidence_refs=[0]),
              Finding(claim="The account made 23 purchases.", evidence_refs=[0])]
    v = verify_claims(claims, [SIGNAL_EVIDENCE])
    assert [x.finding_index for x in v] == [1]


def test_a_small_decimal_is_checked_because_scores_live_there():
    """A score of 0.9997 is below the small-number exemption, and a claim that it was 0.42
    must not slip through on that technicality."""
    ev = [Evidence(tool="decision", payload={"mlScore": 0.9997, "signals": [{"severity": 0.25}]})]
    wrong = verify_claims([Finding(claim="The model scored it 0.42.", evidence_refs=[0])], ev)
    assert [v.kind for v in wrong] == ["uncited_number"]
    right = [Finding(claim="The model scored it 0.9997, and the signal's severity was 0.25.", evidence_refs=[0])]
    assert verify_claims(right, ev) == []


def test_a_rounded_score_is_still_supported():
    ev = [Evidence(tool="decision", payload={"mlScore": 0.9997944})]
    assert verify_claims([Finding(claim="It scored 0.9998.", evidence_refs=[0])], ev) == []


def test_small_whole_numbers_stay_exempt():
    ev = [Evidence(tool="t", payload={"count": 18})]
    assert verify_claims([Finding(claim="Two signals fired, 18 payments, 1 account.", evidence_refs=[0])], ev) == []
    assert verify_claims([Finding(claim="Two signals, 18 payments, 2.0 accounts.", evidence_refs=[0])], ev) == []


def test_digits_inside_a_uuid_support_nothing():
    ev = [Evidence(tool="decision", payload={"txnId": "1af96d0e-5b18-4c3e-9f91-e70712a598da", "count": 9})]
    assert [v.kind for v in verify_claims([Finding(claim="It happened 18 times.", evidence_refs=[0])], ev)] \
        == ["uncited_number"]
    # and quoting the id itself is not a quantity either
    assert verify_claims([Finding(claim="Transaction 1af96d0e-5b18-4c3e-9f91-e70712a598da, 9 payments.",
                                  evidence_refs=[0])], ev) == []


def test_the_number_of_keys_in_an_object_is_not_evidence():
    ev = [Evidence(tool="decision", payload={f"k{i}": "x" for i in range(12)})]
    assert [v.kind for v in verify_claims([Finding(claim="Flagged 12 times.", evidence_refs=[0])], ev)] \
        == ["uncited_number"]



@pytest.mark.parametrize("claim", ["amtZ = -0.38", "amtZ = \u22120.38", "amtZ = \u20110.38", "0.38 below its average"])
def test_a_negative_value_can_be_quoted_with_any_minus_sign_or_in_words(claim):
    ev = [Evidence(tool="decision", payload={"features": {"amtZ": -0.38}})]
    assert verify_claims([Finding(claim=claim, evidence_refs=[0])], ev) == []


def test_a_wrong_magnitude_is_still_caught_whatever_the_sign():
    ev = [Evidence(tool="decision", payload={"features": {"amtZ": -0.38}})]
    assert [v.kind for v in verify_claims([Finding(claim="amtZ = \u22120.39", evidence_refs=[0])], ev)] \
        == ["uncited_number"]


def test_a_derived_rate_is_caught():
    """Seen live: 81 transactions over 24 hours became "about 3-4 an hour"."""
    ev = [Evidence(tool="get_user_history", payload={"recentTruncatedFrom": 81, "hours": 24})]
    claim = "It normally makes about 3\u20114 transactions per hour (81 over 24 h)."
    violations = verify_claims([Finding(claim=claim, evidence_refs=[0])], ev)
    assert {v.kind for v in violations} == {"uncited_number"}
    assert any("quotes 4," in v.detail for v in violations)
    assert not any("quotes 81" in v.detail or "quotes 24" in v.detail for v in violations)



@pytest.mark.parametrize("claim", ["a component of 13\u202f805 accounts", "a component of 13\u00a0805 accounts",
                                   "a component of 13,805 accounts", "a component of 13805 accounts"])
def test_thousands_separators_written_as_spaces_are_one_number(claim):
    """Seen live: "13 805" with a narrow no-break space was read as 13 and 805."""
    ev = [Evidence(tool="decision", payload={"componentSize": 13805})]
    assert verify_claims([Finding(claim=claim, evidence_refs=[0])], ev) == []


def test_a_space_before_digits_that_are_not_a_group_still_separates_numbers():
    ev = [Evidence(tool="t", payload={"a": 18, "b": 60})]
    assert extract_numbers("18\u00a060 seconds") == [18.0, 60.0]       # two digits after: not a separator
    assert extract_numbers("5\u202f1234") == [5.0, 1234.0]            # four digits after: not a separator
    assert verify_claims([Finding(claim="18\u00a060 seconds", evidence_refs=[0])], ev) == []



def test_citation_markers_written_into_the_prose_are_not_quantities():
    """Seen live: "... closed as fraud (evidence [3])" failed because [3] was read as the number 3."""
    ev = [Evidence(tool="t", payload={"count": 18})] * 4
    assert extract_numbers("closed as fraud (evidence [3]), see also [0, 2]") == []
    assert verify_claims([Finding(claim="18 payments, as shown in [3].", evidence_refs=[3])], ev) == []
    # a bracketed number that is part of the claim's wording, not a marker, is still checked
    assert [v.kind for v in verify_claims([Finding(claim="It happened 57 times [3].", evidence_refs=[3])], ev)] \
        == ["uncited_number"]
