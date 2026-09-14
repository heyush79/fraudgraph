"""FastAPI front door. The case service posts here, fire and forget, when a case opens.

    python -m agent.server

`/investigate` returns 202 immediately and runs the graph in the background: an
investigation takes tens of seconds and the case service must not block its Kafka consumer
waiting for it. The agent is never on the decisioning path, and it is not on the
case-creation path either.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel
from starlette.responses import PlainTextResponse

from .graph import build_graph
from .indexer import index_closed_cases
from .llm import build_llm, check_model
from .memory import build_memory
from .settings import Settings
from .tools import Tools

log = logging.getLogger("agent")

INVESTIGATIONS = Counter("agent_investigations_total", "Investigations run", ["outcome"])
DURATION = Histogram("agent_investigation_seconds", "Wall time per investigation",
                     buckets=(1, 2, 5, 10, 20, 40, 80, 160))
TOOL_CALLS = Histogram("agent_tool_calls", "Tool calls used per investigation",
                       buckets=(0, 1, 2, 3, 4, 5, 6, 7, 8))
VERIFY_FAILURES = Counter("agent_verify_failures_total", "Reports that failed the citation check")


class InvestigateRequest(BaseModel):
    caseId: str


# Investigations share a per-minute token budget with each other, so running two at once
# makes both slow rather than one fast. Serialised by default; see settings.max_concurrent.
_RUN_LOCK = threading.BoundedSemaphore(Settings().max_concurrent)
QUEUED = Gauge("agent_investigations_waiting", "Investigations waiting for a slot")


def investigate_case(case_id: str, settings: Settings, graph) -> dict[str, Any]:
    """Runs the graph to completion. Never raises; a failed investigation is a counted
    outcome, because the case still needs to be workable by a human either way."""
    QUEUED.inc()
    with _RUN_LOCK:
        QUEUED.dec()
        return _run(case_id, graph)


def _run(case_id: str, graph) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        final = graph.invoke({"case_id": case_id}, {"recursion_limit": 50})
        report = final.get("report") or {}
        verification = report.get("verification") or {}
        passed = bool(verification.get("passed"))
        if not passed:
            VERIFY_FAILURES.inc()
        INVESTIGATIONS.labels(outcome="verified" if passed else "escalated").inc()
        TOOL_CALLS.observe(verification.get("toolCallsUsed", 0))
        log.info("case %s: %s in %.1fs, %s tool calls, %d evidence",
                 case_id, "verified" if passed else "escalated",
                 time.perf_counter() - started, verification.get("toolCallsUsed"),
                 verification.get("evidenceCount", 0))
        return final
    except Exception as e:  # noqa: BLE001
        INVESTIGATIONS.labels(outcome="error").inc()
        log.exception("investigation of case %s failed", case_id)
        return {"case_id": case_id, "error": str(e)}
    finally:
        DURATION.observe(time.perf_counter() - started)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="fraudgraph-analyst-agent", version="0.1.0")
    state: dict[str, Any] = {}

    async def _refresh_index_forever() -> None:
        while True:
            await asyncio.sleep(settings.index_refresh_secs)
            memory = state.get("memory")
            if memory is not None and memory.count() >= 0:
                await asyncio.to_thread(index_closed_cases, settings.case_service_url, memory)

    def _init_memory() -> None:
        """Chroma construction can take a while on a cold cache, so it happens off the
        startup path. Until it is ready `find_similar_cases` reports an error, which the
        verify node already refuses to let any claim cite: the agent degrades to working
        without precedent rather than refusing to start."""
        memory = build_memory(settings)
        state["memory"] = memory
        state["tools"]._memory = memory
        log.info("similar-case memory ready, %d closed case(s) indexed", memory.count())

    @app.on_event("startup")
    def _startup() -> None:
        from .memory import NullMemory
        tools = Tools(settings, memory=NullMemory())
        state["tools"] = tools
        state["memory"] = NullMemory()
        threading.Thread(target=_init_memory, name="memory-init", daemon=True).start()
        try:
            state["graph"] = build_graph(settings, tools, build_llm(settings))
            state["error"] = check_model(settings)      # usable client, unusable model id
            if state["error"]:
                log.error("%s", state["error"])
            log.info("agent ready: provider=%s model=%s budget=%d tool calls",
                     settings.provider, settings.model, settings.max_tool_calls)
        except Exception as e:  # noqa: BLE001 - serve /health so the operator can see why
            state["graph"] = None
            state["error"] = str(e)
            log.error("agent cannot serve investigations: %s", e)
        state["indexer"] = asyncio.get_event_loop().create_task(_refresh_index_forever())

    @app.on_event("shutdown")
    def _shutdown() -> None:
        task = state.get("indexer")
        if task is not None:
            task.cancel()
        if state.get("tools") is not None:
            state["tools"].close()

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "UP" if state.get("graph") and not state.get("error") else "NO_MODEL",
            "provider": settings.provider,
            "model": settings.model,
            "maxToolCalls": settings.max_tool_calls,
            "maxConcurrent": settings.max_concurrent,
            "similarCasesIndexed": state["memory"].count() if state.get("memory") else 0,
            "error": state.get("error"),
        }

    @app.post("/investigate", status_code=202)
    def investigate(req: InvestigateRequest, background: BackgroundTasks) -> dict:
        if not state.get("graph"):
            raise HTTPException(status_code=503, detail=state.get("error") or "no model configured")
        background.add_task(investigate_case, req.caseId, settings, state["graph"])
        return {"accepted": req.caseId}

    @app.post("/investigate/sync")
    def investigate_sync(req: InvestigateRequest) -> dict:
        """Blocking variant, used by the eval harness where the result is the point."""
        if not state.get("graph"):
            raise HTTPException(status_code=503, detail=state.get("error") or "no model configured")
        final = investigate_case(req.caseId, settings, state["graph"])
        return {"caseId": req.caseId, "report": final.get("report"), "notes": final.get("notes")}

    @app.post("/reindex")
    def reindex() -> dict:
        """Refresh the similar-case index now instead of waiting for the timer."""
        n = index_closed_cases(settings.case_service_url, state["memory"])
        return {"indexed": n, "total": state["memory"].count()}

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.server_port, log_level="warning")


if __name__ == "__main__":
    main()
