from __future__ import annotations

import json
from typing import Any

import pytest

from agent.settings import Settings

# A real BLOCK decision captured off the live topic, with the merchant fields Phase 5 added.
DECISION = {
    "txnId": "fc7746f4-de85-4b02-b456-c8e3c18a5473",
    "userId": "u_10903",
    "merchantId": "m_GIFT_0007",
    "merchantCategory": "GIFT",
    "verdict": "BLOCK", "mode": "FULL", "mlScore": 0.9997,
    "firedRules": ["VELOCITY_1M", "VELOCITY_5M"],
    "signals": [
        {"code": "VELOCITY_1M", "severity": 1.0,
         "evidence": {"count": 18, "limit": 8, "windowSecs": 60, "sum": 4353.64}},
        {"code": "VELOCITY_5M", "severity": 0.2,
         "evidence": {"count": 24, "limit": 20, "windowSecs": 300, "sum": 8156.11}},
    ],
    "features": {"cnt1m": 18, "cnt5m": 24, "cnt1h": 37, "channel": "CARD", "merchantRiskTier": 3},
    "latencyMs": 25, "decidedAt": "2026-09-12T13:28:17.120Z",
}

CASE = {
    "caseId": "3f2a0000-0000-4000-8000-000000000001",
    "txnId": DECISION["txnId"], "userId": "u_10903", "verdict": "BLOCK",
    "mlScore": 0.9997, "status": "OPEN", "firedRules": DECISION["firedRules"],
    "decisionDoc": DECISION, "reportDoc": None, "events": [],
}

WINDOWS = {"cnt1m": 18, "sum1m": 4353.64, "cnt5m": 24, "sum5m": 8156.11, "cnt1h": 37, "sum1h": 25423.32}


class FakeTools:
    """Stands in for the HTTP clients. Records what the graph asked for."""

    def __init__(self, **overrides: Any) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.attached: dict | None = None
        self.overrides = overrides

    def _ev(self, tool: str, args: dict, payload: Any = None, error: str | None = None):
        from agent.models import Evidence
        self.calls.append((tool, args))
        if tool in self.overrides:
            payload, error = self.overrides[tool], None
            if isinstance(payload, Exception):
                return Evidence(tool=tool, args=args, error=str(payload))
        return Evidence(tool=tool, args=args, payload=payload, error=error)

    def get_case(self, case_id):
        return self._ev("get_case", {"case_id": case_id}, CASE)

    def get_user_history(self, user_id, hours=24):
        return self._ev("get_user_history", {"user_id": user_id, "hours": hours},
                        {"userId": user_id, "profile": {"n": 41, "mean": 812.4, "std": 690.1},
                         "windows": WINDOWS, "recent": []})

    def get_window_counts(self, user_id):
        return self._ev("get_window_counts", {"user_id": user_id}, WINDOWS)

    def get_graph_neighborhood(self, user_id, depth=2):
        return self._ev("get_graph_neighborhood", {"user_id": user_id, "depth": depth},
                        {"nodes": [{"id": user_id, "degree": 0}], "edges": [], "cycles": [], "componentSize": 1})

    def find_similar_cases(self, summary_text, k=3):
        return self._ev("find_similar_cases", {"summary_text": summary_text[:50], "k": k}, [])

    def attach_report(self, case_id, report):
        self.attached = report
        return True


# A turn with no tool calls and no JSON. Investigate treats it as "done gathering"; it is
# never a valid draft.
STOP = ""


class ScriptedLLM:
    """Replays a list of turns, so a whole graph run is deterministic and needs no API key.

    Each turn is either {"tools": [(name, args), ...]} to request tool calls, or a value
    that becomes the message content (a dict is serialized, which is how a draft is given).

    The graph consumes one turn per model call, and the order is not obvious, so scripts
    read as cycles:

        {"tools": [...]},   # investigate asks for tools; the loop comes back for another turn
        STOP,               # investigate declines further tools, so the loop exits
        DRAFT,              # draft_report

    A verification failure routes back to investigate, which needs its own STOP (or more
    tool turns) before the next DRAFT. Getting this wrong is silent: a draft turn that
    receives a tool request sees empty content and reports "no parseable JSON".
    """

    def __init__(self, turns: list[Any]) -> None:
        self.turns = list(turns)
        self.seen: list[Any] = []

    def bind_tools(self, schemas):
        return self

    def invoke(self, messages):
        self.seen.append(messages)
        turn = self.turns.pop(0) if self.turns else ""
        if isinstance(turn, dict) and "tools" in turn:
            calls = [{"name": n, "args": a, "id": f"call-{i}"} for i, (n, a) in enumerate(turn["tools"])]
            return _Reply("", calls)
        if isinstance(turn, Exception):
            raise turn
        return _Reply(turn if isinstance(turn, str) else json.dumps(turn), [])


class _Reply:
    def __init__(self, content: str, tool_calls: list[dict]) -> None:
        self.content = content
        self.tool_calls = tool_calls


@pytest.fixture
def settings() -> Settings:
    return Settings(provider="scripted", model="fake", max_tool_calls=8, max_verify_attempts=2)
