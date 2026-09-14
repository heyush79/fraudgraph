"""The agent's four tools (LLD §6.1).

Every one is a thin HTTP client to our own services, or local vector search. The agent has
no database handle, no Kafka client and no direct access to the engine's state stores: it
can only learn what these functions return. That boundary is deliberate and is the honest
answer to "how do you stop the LLM doing something unexpected" — it cannot reach anything.

Tools never raise. A failed call becomes an Evidence entry carrying `error`, which the
verify node then refuses to let any claim cite. A tool outage degrades the report instead
of crashing the run.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import Evidence
from .settings import Settings

log = logging.getLogger(__name__)


class Tools:
    """Bound to one case-service instance and one Chroma collection."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None, memory: Any = None) -> None:
        self._s = settings
        self._http = client or httpx.Client(base_url=settings.case_service_url, timeout=settings.http_timeout_s)
        self._memory = memory

    # -- the case itself (not a model-callable tool; the graph fetches it) ---------

    def get_case(self, case_id: str) -> Evidence:
        return self._get(f"/cases/{case_id}", {}, tool="get_case", args={"case_id": case_id})

    # -- model-callable tools -----------------------------------------------------

    def get_user_history(self, user_id: str, hours: int = 24) -> Evidence:
        """Recent decisions for this account plus its live amount profile."""
        hours = max(1, min(168, int(hours)))
        ev = self._get(f"/internal/users/{user_id}/history", {"hours": hours},
                       tool="get_user_history", args={"user_id": user_id, "hours": hours})
        # Fifty decisions is more than the model needs and more than the token budget allows.
        # Trimming here rather than in the prompt keeps the evidence and what the model saw
        # identical, which matters because the verify node checks claims against the evidence.
        if ev.ok() and isinstance(ev.payload, dict):
            recent = ev.payload.get("recent")
            if isinstance(recent, list) and len(recent) > self._s.history_limit:
                ev.payload["recent"] = recent[: self._s.history_limit]
                ev.payload["recentTruncatedFrom"] = len(recent)
        return ev

    def get_window_counts(self, user_id: str) -> Evidence:
        """Live 1m / 5m / 1h transaction counts and sums, straight from the engine's stores."""
        return self._get(f"/internal/users/{user_id}/windows", {},
                         tool="get_window_counts", args={"user_id": user_id})

    def get_graph_neighborhood(self, user_id: str, depth: int = 2) -> Evidence:
        """P2P transfers around this account, any cycles it sits on, and its component size."""
        depth = max(1, min(2, int(depth)))
        return self._get(f"/internal/graph/{user_id}/neighborhood", {"depth": depth},
                         tool="get_graph_neighborhood", args={"user_id": user_id, "depth": depth})

    def find_similar_cases(self, summary_text: str, k: int | None = None) -> Evidence:
        """Past closed cases whose reports read like this one, with how they were resolved."""
        k = k or self._s.similar_k
        args = {"summary_text": summary_text[:500], "k": k}
        if self._memory is None:
            return Evidence(tool="find_similar_cases", args=args, error="similar-case memory is not configured")
        try:
            return Evidence(tool="find_similar_cases", args=args, payload=self._memory.search(summary_text, k))
        except Exception as e:  # noqa: BLE001 - a vector-store failure must not end the run
            log.warning("similar-case search failed: %s", e)
            return Evidence(tool="find_similar_cases", args=args, error=str(e))

    # -- report write-back ---------------------------------------------------------

    def attach_report(self, case_id: str, report: dict[str, Any]) -> bool:
        try:
            r = self._http.put(f"/internal/cases/{case_id}/report", json=report)
            r.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("could not attach the report for case %s: %s", case_id, e)
            return False

    # -- plumbing ------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any], tool: str, args: dict[str, Any]) -> Evidence:
        try:
            r = self._http.get(path, params=params)
            if r.status_code == 404:
                return Evidence(tool=tool, args=args, error="not found")
            r.raise_for_status()
            return Evidence(tool=tool, args=args, payload=r.json())
        except Exception as e:  # noqa: BLE001
            log.warning("tool %s failed: %s", tool, e)
            return Evidence(tool=tool, args=args, error=str(e))

    def close(self) -> None:
        self._http.close()


# The schemas the model sees. Kept as plain dicts rather than decorators so the same
# definitions can be bound to any provider's tool-calling API.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_user_history",
        "description": ("Recent decisions for one account over the last N hours, plus its rolling "
                        "amount profile (count, mean, standard deviation). Use this to judge whether "
                        "the transaction under investigation is normal for this account."),
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "account id, e.g. u_10903"},
                "hours": {"type": "integer", "description": "how far back to look, 1 to 168", "default": 24},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "get_window_counts",
        "description": ("Live transaction counts and amount sums for one account over the last "
                        "1 minute, 5 minutes and 1 hour, read from the decision engine's own state. "
                        "Use this to confirm or refute a velocity signal."),
        "parameters": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"],
        },
    },
    {
        "name": "get_graph_neighborhood",
        "description": ("Peer-to-peer transfers around one account up to `depth` hops, any payment "
                        "cycles the account sits on, and the size of its connected component. Use "
                        "this to confirm or refute a ring signal, or to find accomplices."),
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "depth": {"type": "integer", "description": "1 or 2", "default": 2},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "find_similar_cases",
        "description": ("Past closed cases whose analyst reports resemble the text you pass, with "
                        "how each was resolved. Use this to check whether this pattern has been "
                        "seen before and what the outcome was."),
        "parameters": {
            "type": "object",
            "properties": {
                "summary_text": {"type": "string", "description": "a short description of this case"},
                "k": {"type": "integer", "default": 3},
            },
            "required": ["summary_text"],
        },
    },
]

CALLABLE_TOOLS = {s["name"] for s in TOOL_SCHEMAS}
