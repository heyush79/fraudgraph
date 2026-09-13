"""grpc.aio scoring server + FastAPI admin in one process.

    python -m scorer.server

Loads the latest registry version at startup (or serves FAILED_PRECONDITION until one is
trained — the stream engine's breaker then keeps it in DEGRADED mode, by design).
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import grpc
import uvicorn

from api.admin import create_app

from . import metrics
from .features import row_from_proto
from .gen import scoring_pb2, scoring_pb2_grpc
from .model import ModelHolder, Registry
from .settings import Settings

log = logging.getLogger("scorer")


class ScoringServicer(scoring_pb2_grpc.ScoringServiceServicer):
    def __init__(self, holder: ModelHolder, executor: ThreadPoolExecutor, shap_min_probability: float) -> None:
        self._holder = holder
        self._executor = executor
        self._shap_min = shap_min_probability

    async def Score(self, request: scoring_pb2.FeatureVector, context: grpc.aio.ServicerContext) -> scoring_pb2.ScoreResult:
        started = time.perf_counter()
        bundle = self._holder.current
        if bundle is None:
            metrics.REQUESTS.labels(outcome="no_model").inc()
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "no model loaded; run training first")
        try:
            row = row_from_proto(request)
            loop = asyncio.get_running_loop()
            pred = await loop.run_in_executor(self._executor, bundle.predict, row, self._shap_min)
        except Exception as e:  # noqa: BLE001 - any failure must surface as a gRPC status, never hang
            metrics.REQUESTS.labels(outcome="error").inc()
            log.exception("scoring failed for txn %s", request.txn_id)
            await context.abort(grpc.StatusCode.INTERNAL, f"scoring failed: {e}")
        metrics.REQUESTS.labels(outcome="ok").inc()
        metrics.SCORE.observe(pred.probability)
        metrics.LATENCY.observe(time.perf_counter() - started)
        return scoring_pb2.ScoreResult(
            probability=pred.probability,
            contributions=[scoring_pb2.Contribution(feature=f, shap=s) for f, s in pred.contributions],
            model_version=pred.model_version,
        )


async def build_grpc_server(holder: ModelHolder, settings: Settings, port: int | None = None) -> tuple[grpc.aio.Server, int]:
    executor = ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="score")
    server = grpc.aio.server(migration_thread_pool=executor)
    scoring_pb2_grpc.add_ScoringServiceServicer_to_server(
        ScoringServicer(holder, executor, settings.shap_min_probability), server
    )
    bound = server.add_insecure_port(f"[::]:{settings.grpc_port if port is None else port}")
    return server, bound


async def serve(settings: Settings | None = None) -> None:
    settings = settings or Settings()
    holder = ModelHolder(Registry(settings.registry))
    bundle = holder.try_load_latest()
    if bundle:
        metrics.MODEL_VERSION.set(int(bundle.version[1:]))
        log.info("loaded model %s from %s", bundle.version, settings.registry)
    else:
        log.warning("no model in %s — serving FAILED_PRECONDITION until `make train` runs", settings.registry)

    server, port = await build_grpc_server(holder, settings)
    await server.start()
    log.info("gRPC scoring on :%d, admin on :%d", port, settings.admin_port)

    admin = uvicorn.Server(uvicorn.Config(create_app(holder), host="0.0.0.0", port=settings.admin_port, log_level="warning"))
    try:
        await admin.serve()          # returns on SIGINT/SIGTERM
    finally:
        await server.stop(grace=5)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(serve())


if __name__ == "__main__":
    main()
