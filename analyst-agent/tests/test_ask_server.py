"""The HTTP surface of the ask endpoint: status codes, the cache and the rate limit."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent import server
from agent.memory import NullMemory
from agent.settings import Settings

from .conftest import CASE, FakeTools, ScriptedLLM

GOOD = {"sentences": [{"text": "The account made 18 transactions in 60 seconds.", "refs": [0]}]}
URL = f"/cases/{CASE['caseId']}/ask"


@pytest.fixture
def make_client(monkeypatch):
    def _make(llm=None, tools=None, llm_error: Exception | None = None, **settings_kw):
        tools = tools or FakeTools()

        def build_llm(_settings):
            if llm_error is not None:
                raise llm_error
            return llm

        monkeypatch.setattr(server, "Tools", lambda _s, memory=None: tools)
        monkeypatch.setattr(server, "build_llm", build_llm)
        monkeypatch.setattr(server, "check_model", lambda _s: None)
        monkeypatch.setattr(server, "build_graph", lambda *_a: object())
        monkeypatch.setattr(server, "build_memory", lambda _s: NullMemory())
        settings = Settings(provider="scripted", model="fake", **settings_kw)
        return TestClient(server.create_app(settings))
    return _make


def test_a_question_is_answered(make_client):
    with make_client(ScriptedLLM([GOOD])) as client:
        r = client.post(URL, json={"question": "Why was this transaction flagged?"})
    assert r.status_code == 200
    body = r.json()
    assert body["caseId"] == CASE["caseId"] and body["answer"][0]["refs"] == [0]
    assert body["evidence"][0]["tool"] == "decision"


def test_the_same_question_is_served_from_the_cache_without_another_model_call(make_client):
    llm = ScriptedLLM([GOOD])
    with make_client(llm) as client:
        first = client.post(URL, json={"question": "Why was this transaction flagged?"}).json()
        second = client.post(URL, json={"question": "why was this transaction flagged"}).json()
    assert len(llm.seen) == 1
    assert second["cached"] is True and second["answer"] == first["answer"]


def test_the_rate_limit_answers_429_with_retry_after(make_client):
    llm = ScriptedLLM([GOOD, GOOD])
    with make_client(llm, ask_rate_global_per_min=1) as client:
        assert client.post(URL, json={"question": "first question"}).status_code == 200
        r = client.post(URL, json={"question": "a different question"})
        # a cached answer costs nothing, so it is still served while limited
        cached = client.post(URL, json={"question": "first question"})
    assert r.status_code == 429 and 1 <= int(r.headers["Retry-After"]) <= 61
    assert cached.status_code == 200
    assert len(llm.seen) == 1


def test_the_limit_is_per_client_behind_the_tunnel(make_client):
    with make_client(ScriptedLLM([GOOD, GOOD]), ask_rate_ip_per_min=1) as client:
        a = client.post(URL, json={"question": "q1"}, headers={"CF-Connecting-IP": "1.1.1.1"})
        a2 = client.post(URL, json={"question": "q2"}, headers={"CF-Connecting-IP": "1.1.1.1"})
        b = client.post(URL, json={"question": "q3"}, headers={"CF-Connecting-IP": "2.2.2.2"})
    assert (a.status_code, a2.status_code, b.status_code) == (200, 429, 200)


def test_an_unknown_case_is_404(make_client):
    with make_client(ScriptedLLM([GOOD]), tools=FakeTools(get_case=RuntimeError("not found"))) as client:
        assert client.post(URL, json={"question": "why?"}).status_code == 404


def test_an_unreachable_case_service_is_503(make_client):
    with make_client(ScriptedLLM([GOOD]), tools=FakeTools(get_case=RuntimeError("connection refused"))) as client:
        assert client.post(URL, json={"question": "why?"}).status_code == 503


def test_no_model_is_503_and_health_says_so(make_client):
    with make_client(llm_error=RuntimeError("GROQ_API_KEY is not set")) as client:
        r = client.post(URL, json={"question": "why?"})
        health = client.get("/health").json()
    assert r.status_code == 503 and "GROQ_API_KEY" in r.json()["detail"]
    assert health["status"] == "NO_MODEL"


def test_an_empty_or_huge_question_is_rejected(make_client):
    with make_client(ScriptedLLM([])) as client:
        assert client.post(URL, json={"question": ""}).status_code == 422
        assert client.post(URL, json={"question": "x" * 501}).status_code == 422


def test_health_reports_the_chat_settings(make_client):
    with make_client(ScriptedLLM([]), ask_rate_global_per_min=3) as client:
        health = client.get("/health").json()
    assert health["status"] == "UP"
    assert health["ask"] == {"rateLimited": True, "cacheTtlSeconds": 3600}
