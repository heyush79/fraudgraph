"""Feeds closed cases into the similar-case memory.

LLD §6.2 says closed reports get embedded, not open ones: an open case has no outcome to
learn from, and indexing it would let the agent cite its own earlier guess back to itself as
precedent. The agent has no database access, so it discovers closed cases the same way
everything else does, by asking the case service.

Runs as a periodic background task rather than at report time, because a case is closed by a
human minutes or hours after the report is written.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

CLOSED_STATUSES = ("CLOSED_FRAUD", "CLOSED_FP")


def summary_text(case: dict[str, Any]) -> str:
    """What gets embedded. The report's own summary plus the codes that fired, so retrieval
    matches on both the narrative and the mechanism."""
    report = case.get("reportDoc") or {}
    fired = ", ".join(case.get("firedRules") or [])
    parts = [report.get("summary") or "", f"signals: {fired}" if fired else "",
             f"type: {report.get('fraud_type', 'UNKNOWN')}"]
    return " ".join(p for p in parts if p).strip()


def index_closed_cases(case_service_url: str, memory, timeout: float = 10.0, page: int = 200) -> int:
    """Upserts every closed case that has a report. Returns how many were indexed."""
    indexed = 0
    try:
        with httpx.Client(base_url=case_service_url, timeout=timeout) as http:
            for status in CLOSED_STATUSES:
                offset = 0
                while True:
                    r = http.get("/cases", params={"status": status, "limit": page, "offset": offset})
                    r.raise_for_status()
                    body = r.json()
                    items = body.get("items") or []
                    if not items:
                        break
                    for summary in items:
                        detail = http.get(f"/cases/{summary['caseId']}").json()
                        if not detail.get("reportDoc"):
                            continue          # closed without the agent ever reporting
                        text = summary_text(detail)
                        if not text:
                            continue
                        memory.index(detail["caseId"], text, {
                            "outcome": status,
                            "verdict": detail.get("verdict"),
                            "fraudType": (detail.get("reportDoc") or {}).get("fraud_type"),
                            "userId": detail.get("userId"),
                            "closedAt": detail.get("updatedAt"),
                        })
                        indexed += 1
                    offset += len(items)
                    if offset >= body.get("total", 0):
                        break
    except Exception as e:  # noqa: BLE001 - a stale index is survivable, a crashed agent is not
        log.warning("could not refresh the similar-case index: %s", e)
    if indexed:
        log.info("similar-case index refreshed: %d closed case(s)", indexed)
    return indexed
