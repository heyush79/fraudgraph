from __future__ import annotations

import copy

import pytest

from agent.ask import (AnswerCache, CaseNotFound, CaseUnavailable, ask_case, initial_evidence, parse_draft,
                       route_question)

from .conftest import CASE, DECISION, WINDOWS, FakeTools, ScriptedLLM


def say(*sentences: tuple[str, list[int]]) -> dict:
    return {"sentences": [{"text": t, "refs": r} for t, r in sentences]}


def ask(llm, tools=None, settings=None, question="Why was this transaction flagged?", history=None):
    from agent.settings import Settings
    return ask_case(CASE["caseId"], question, history, settings or Settings(provider="scripted", model="fake"),
                    tools or FakeTools(), llm)


def test_a_supported_answer_takes_one_model_call_and_cites_the_decision():
    llm = ScriptedLLM([say(("The account made 18 transactions in 60 seconds, against a limit of 8.", [0]),
                           ("The model scored it 0.9997.", [0]))])
    tools = FakeTools()
    out = ask(llm, tools)

    assert len(llm.seen) == 1
    assert [s["text"] for s in out["answer"]] == [
        "The account made 18 transactions in 60 seconds, against a limit of 8.", "The model scored it 0.9997."]
    assert all(s["verified"] for s in out["answer"])
    assert out["removed"] == []
    assert out["verification"] == {"passed": True, "attempts": 1, "violations": []}
    assert out["evidence"][0]["tool"] == "decision" and out["evidence"][0]["payload"] == DECISION
    assert [t for t, _ in tools.calls] == ["get_case"]            # no tool spend on the common path
    assert out["mode"] == "live" and out["model"] == "fake"
    assert [s["kind"] for s in out["steps"]] == ["evidence", "draft", "verify"]


def test_an_unsupported_sentence_is_removed_with_its_reason_and_the_rest_survives():
    llm = ScriptedLLM([say(("The account made 18 transactions in 60 seconds.", [0]),
                           ("This account has been flagged 12 times this week.", [0]))])
    out = ask(llm)

    assert [s["text"] for s in out["answer"]] == ["The account made 18 transactions in 60 seconds."]
    assert out["removed"][0]["text"] == "This account has been flagged 12 times this week."
    # the reason says what failed without repeating the sentence it sits next to
    assert out["removed"][0]["reason"] == "claim quotes 12, which does not appear in evidence [0]"
    # something survived, so no second call is spent on a rewrite
    assert len(llm.seen) == 1
    assert out["verification"]["passed"] is True
    assert [v["kind"] for v in out["verification"]["violations"]] == ["uncited_number"]


def test_a_fabricated_score_is_removed_even_though_it_is_below_one():
    out = ask(ScriptedLLM([say(("The model scored it 0.42.", [0]),
                               ("18 transactions arrived in a minute.", [0]))]))
    assert [r["text"] for r in out["removed"]] == ["The model scored it 0.42."]


def test_needs_fetches_tools_with_arguments_taken_from_the_case_not_the_model():
    llm = ScriptedLLM([
        {"needs": ["get_window_counts", "drop_all_tables", "get_user_history", "get_graph_neighborhood"]},
        say(("In the last hour the account made 37 transactions worth 25,423.32.", [1])),
    ])
    tools = FakeTools()
    out = ask(llm, tools, question="What else should I check?")

    # the unknown name is ignored and the budget of two is respected
    assert [t for t, _ in tools.calls] == ["get_case", "get_window_counts", "get_user_history"]
    assert all(args.get("user_id") == DECISION["userId"] for t, args in tools.calls if t != "get_case")
    assert [e["tool"] for e in out["evidence"]] == ["decision", "get_window_counts", "get_user_history"]
    assert [e["index"] for e in out["evidence"]] == [0, 1, 2]
    assert out["evidence"][1]["payload"] == WINDOWS
    assert out["answer"][0]["refs"] == [1]
    assert [s["kind"] for s in out["steps"]] == ["evidence", "draft", "tool", "tool", "draft", "verify"]
    # the second call is told to answer, not to ask again
    assert "Answer now" in llm.seen[1][-1].content


def test_when_every_sentence_fails_it_rewrites_once_with_the_specific_problems():
    llm = ScriptedLLM([say(("It was flagged 12 times.", [0])),
                       say(("It made 18 transactions in a minute.", [0]))])
    out = ask(llm)

    assert len(llm.seen) == 2
    assert "failed verification" in llm.seen[1][-2].content and "12" in llm.seen[1][-2].content
    assert [s["text"] for s in out["answer"]] == ["It made 18 transactions in a minute."]
    # the first draft's claim stays visible as removed: the guard caught it
    assert [r["text"] for r in out["removed"]] == ["It was flagged 12 times."]
    assert out["verification"]["attempts"] == 2 and out["verification"]["passed"] is True


def test_nothing_supportable_gives_an_empty_answer_not_a_guess():
    llm = ScriptedLLM([say(("Flagged 12 times.", [0])), say(("Flagged 14 times.", [0]))])
    out = ask(llm)
    assert out["answer"] == []
    assert out["verification"]["passed"] is False
    assert {r["text"] for r in out["removed"]} == {"Flagged 12 times.", "Flagged 14 times."}


def test_an_unparseable_reply_gets_one_format_reminder():
    llm = ScriptedLLM(["It is clearly fraud, trust me.", say(("18 transactions in a minute.", [0]))])
    out = ask(llm)
    assert "not a JSON object" in llm.seen[1][-2].content
    assert len(out["answer"]) == 1


def test_a_provider_failure_is_reported_in_the_steps_and_not_retried():
    llm = ScriptedLLM([RuntimeError("429 rate limit exceeded")])
    out = ask(llm)
    assert out["answer"] == [] and len(llm.seen) == 1
    draft = [s for s in out["steps"] if s["kind"] == "draft"][0]
    assert "could not be reached" in draft["label"] and "429" in draft["detail"]


def test_a_sentence_citing_a_failed_tool_is_removed():
    llm = ScriptedLLM([{"needs": ["get_user_history"]},
                       say(("The history shows 41 earlier transactions.", [1]),
                           ("18 transactions arrived in a minute.", [0]))])
    out = ask(llm, FakeTools(get_user_history=RuntimeError("503 from the engine")))
    assert out["evidence"][1] == {"index": 1, "tool": "get_user_history",
                                  "args": {"user_id": DECISION["userId"], "hours": 24},
                                  "error": "503 from the engine"}
    assert [r["text"] for r in out["removed"]] == ["The history shows 41 earlier transactions."]
    assert "failed" in out["removed"][0]["reason"]


def test_report_evidence_is_reused_and_reindexed_after_the_decision():
    case = copy.deepcopy(CASE)
    case["reportDoc"] = {"summary": "velocity burst", "evidence": [
        {"index": 0, "tool": "get_case", "args": {"case_id": case["caseId"]}, "payload": {"ignored": True}},
        {"index": 1, "tool": "get_window_counts", "args": {"user_id": "u_10903"}, "payload": WINDOWS},
        {"index": 2, "tool": "get_user_history", "args": {"user_id": "u_10903"}, "error": "503"},
    ]}
    ev = initial_evidence(case)
    assert [e.tool for e in ev] == ["decision", "get_window_counts", "get_user_history"]
    assert ev[1].payload == WINDOWS and ev[2].error == "503"

    llm = ScriptedLLM([say(("It made 37 transactions in the last hour.", [1]))])
    out = ask(llm, FakeTools(get_case=case))
    assert out["answer"][0]["refs"] == [1]
    assert "1 result(s) from the analyst report" not in out["steps"][0]["label"]
    assert "2 result(s)" in out["steps"][0]["label"]


def test_a_percentage_of_a_forwarded_amount_is_supported_by_the_ratio():
    case = copy.deepcopy(CASE)
    case["decisionDoc"] = {**DECISION, "firedRules": ["PASS_THROUGH"], "signals": [{
        "code": "PASS_THROUGH", "severity": 0.667,
        "evidence": {"inboundFrom": "u_14106", "inboundAmount": 41230.5, "outboundAmount": 39612.0,
                     "ratio": 0.961, "secsSinceInbound": 184, "chainDepth": 2, "counterpartyId": "u_20190"}}]}
    llm = ScriptedLLM([say(("It forwarded 96% of the 41,230.5 it received from u_14106 184 seconds earlier.", [0]))])
    out = ask(llm, FakeTools(get_case=case), question="Where did the money come from, and where did it go?")
    assert out["removed"] == [] and len(out["answer"]) == 1


def test_only_the_last_six_turns_of_history_are_sent():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn number {i}"} for i in range(10)]
    llm = ScriptedLLM([say(("18 transactions arrived in a minute.", [0]))])
    ask(llm, history=history)
    prompt = llm.seen[0][1].content
    assert "turn number 3" not in prompt
    assert all(f"turn number {i}" in prompt for i in range(4, 10))


def test_an_unknown_case_raises_not_found():
    with pytest.raises(CaseNotFound):
        ask(ScriptedLLM([]), FakeTools(get_case=RuntimeError("not found")))


def test_an_unreachable_case_service_is_distinguished_from_a_missing_case():
    with pytest.raises(CaseUnavailable):
        ask(ScriptedLLM([]), FakeTools(get_case=RuntimeError("connection refused")))


def test_parse_draft_is_strict_about_shape_and_lenient_about_wrapping():
    d = parse_draft('Sure! ```json\n{"sentences": [{"text": " ok ", "refs": [0, "1", -1, true, 2.0]}, '
                    '{"text": ""}, "junk"]}\n```')
    assert d.sentences == [{"text": "ok", "refs": [0, 2]}]
    assert parse_draft('{"needs": ["get_window_counts", "get_window_counts", 7]}').needs == ["get_window_counts"]
    assert parse_draft("no json at all").sentences == []


class TestAnswerCache:
    ANSWER = {"answer": [{"text": "x", "refs": [0], "verified": True}]}

    def test_hits_ignore_case_whitespace_and_a_trailing_question_mark(self):
        c = AnswerCache(ttl_s=60)
        c.put(AnswerCache.key("c1", "Why was this flagged?", None), self.ANSWER)
        assert c.get(AnswerCache.key("c1", "  why was THIS flagged ", [])) == self.ANSWER
        assert c.get(AnswerCache.key("c2", "Why was this flagged?", None)) is None

    def test_history_is_part_of_the_key(self):
        c = AnswerCache(ttl_s=60)
        c.put(AnswerCache.key("c1", "and then?", [{"role": "user", "content": "a"}]), self.ANSWER)
        assert c.get(AnswerCache.key("c1", "and then?", [{"role": "user", "content": "b"}])) is None

    def test_entries_expire(self):
        now = [0.0]
        c = AnswerCache(ttl_s=60, clock=lambda: now[0])
        k = AnswerCache.key("c1", "q", None)
        c.put(k, self.ANSWER)
        now[0] = 61.0
        assert c.get(k) is None

    def test_an_empty_answer_is_never_cached(self):
        c = AnswerCache(ttl_s=60)
        k = AnswerCache.key("c1", "q", None)
        c.put(k, {"answer": []})
        assert c.get(k) is None

    def test_it_is_bounded(self):
        c = AnswerCache(ttl_s=60, size=2)
        keys = [AnswerCache.key("c", f"q{i}", None) for i in range(3)]
        for k in keys:
            c.put(k, self.ANSWER)
        assert c.get(keys[0]) is None and c.get(keys[2]) == self.ANSWER

    def test_ttl_zero_disables_it(self):
        c = AnswerCache(ttl_s=0)
        k = AnswerCache.key("c1", "q", None)
        c.put(k, self.ANSWER)
        assert c.get(k) is None


def test_a_question_about_what_is_normal_fetches_the_history_before_the_first_draft():
    llm = ScriptedLLM([say(("Its average payment is 812.4 over 41 transactions.", [1]),
                           ("This minute it made 18 transactions.", [0]))])
    tools = FakeTools()
    out = ask(llm, tools, question="Is this normal behaviour for this account?")
    assert [t for t, _ in tools.calls] == ["get_case", "get_user_history"]
    assert len(llm.seen) == 1                          # no round trip spent asking for it
    assert "get_user_history" in llm.seen[0][1].content
    assert [s["kind"] for s in out["steps"]] == ["evidence", "tool", "draft", "verify"]
    assert len(out["answer"]) == 2 and out["removed"] == []


def test_a_question_about_where_the_money_went_fetches_the_graph():
    tools = FakeTools()
    ask(ScriptedLLM([say(("18 transactions in a minute.", [0]))]), tools,
        question="Where did the money come from, and where did it go?")
    assert [t for t, _ in tools.calls] == ["get_case", "get_graph_neighborhood"]


def test_routed_and_requested_tools_share_one_budget_and_are_never_fetched_twice():
    llm = ScriptedLLM([{"needs": ["get_user_history", "get_window_counts", "get_graph_neighborhood"]},
                       say(("18 transactions in a minute.", [0]))])
    tools = FakeTools()
    ask(llm, tools, question="Is this normal for this account?")
    assert [t for t, _ in tools.calls] == ["get_case", "get_user_history", "get_window_counts"]


def test_a_tool_the_report_already_ran_is_not_run_again():
    case = copy.deepcopy(CASE)
    case["reportDoc"] = {"evidence": [{"index": 1, "tool": "get_user_history", "args": {"user_id": "u_10903"},
                                       "payload": {"profile": {"n": 41}}}]}
    tools = FakeTools(get_case=case)
    ask(ScriptedLLM([say(("18 transactions in a minute.", [0]))]), tools, question="Is this usual for them?")
    assert [t for t, _ in tools.calls] == ["get_case"]


@pytest.mark.parametrize("question, tools", [
    ("Why was this transaction flagged?", []),
    ("What evidence would change the verdict?", []),
    ("Could this be a real trip?", []),
    ("What happened during the last hour?", []),               # "during" is not a ring
    ("Is this normal behaviour for this account?", ["get_user_history"]),
    ("Could this be a genuine shopping spree?", ["get_user_history"]),
    ("Where did the money come from, and where did it go?", ["get_graph_neighborhood"]),
    ("Is it part of a ring?", ["get_graph_neighborhood"]),
    ("Have similar cases been resolved before?", ["get_user_history", "find_similar_cases"]),
])
def test_routing(question, tools):
    assert route_question(question) == tools


def test_the_history_is_shown_as_a_view_without_live_counts_or_latencies():
    from agent.ask import history_view
    raw = {"userId": "u_1", "hours": 24, "profile": {"n": 81, "mean": 537.75, "std": 484.74},
           "windows": {"cnt1m": 0, "cnt5m": 19}, "recentTruncatedFrom": 29,
           "recent": [{"txnId": "t", "verdict": "BLOCK", "firedRules": ["VELOCITY_1M"], "mlScore": 0.99995386,
                       "latencyMs": 12, "decidedAt": "2026-09-29T15:38:07Z", "caseId": "c"}] * 7}
    view = history_view(raw)
    assert view["amountProfileLifetime"] == {"transactions": 81, "meanAmount": 537.75, "stdAmount": 484.74}
    assert view["decisionsInPeriod"] == 29 and view["periodHours"] == 24
    assert len(view["latestDecisions"]) == 5
    assert view["latestDecisions"][0] == {"verdict": "BLOCK", "firedRules": ["VELOCITY_1M"], "mlScore": 1.0,
                                          "decidedAt": "2026-09-29T15:38:07Z"}
    flat = str(view)
    assert "windows" not in flat and "latencyMs" not in flat and "cnt5m" not in flat


def test_a_claim_reading_live_counts_as_usual_has_nothing_to_cite():
    """The failure seen live: "the account usually makes 19 payments in five minutes"."""
    llm = ScriptedLLM([say(("The account usually makes 19 payments in five minutes.", [1]),
                           ("This minute it made 18 transactions.", [0]))])
    tools = FakeTools(get_user_history={"userId": "u_10903", "hours": 24, "profile": {"n": 41, "mean": 812.4, "std": 690.1},
                                        "windows": {"cnt1m": 0, "cnt5m": 19, "cnt1h": 29}, "recent": []})
    out = ask(llm, tools, question="Is this normal behaviour for this account?")
    assert [r["text"] for r in out["removed"]] == ["The account usually makes 19 payments in five minutes."]
