"""FastAPI admin surface (LLD §4.2): /health, /model, /reload?version=vN, /metrics."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from scorer import metrics
from scorer.model import ModelHolder


def create_app(holder: ModelHolder) -> FastAPI:
    app = FastAPI(title="fraudgraph-ml-scorer", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        bundle = holder.current
        return {
            "status": "UP" if bundle else "NO_MODEL",
            "modelVersion": bundle.version if bundle else None,
            "available": holder.registry.versions(),
            # served features this model was not trained on, e.g. right after a proto change
            **({"unusedFeatures": bundle.unused} if bundle and bundle.unused else {}),
            # present only when something was skipped, so an operator sees WHY there is no model
            **({"incompatible": holder.incompatible} if holder.incompatible else {}),
        }

    @app.get("/model")
    def model() -> dict:
        bundle = holder.current
        if bundle is None:
            raise HTTPException(status_code=404, detail="no model loaded")
        return bundle.meta

    @app.post("/reload")
    def reload(version: str | None = Query(default=None, pattern=r"^v\d+$")) -> dict:
        try:
            bundle = holder.load(version)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            # needs a feature this build does not produce; serving it would mean inventing a column
            raise HTTPException(status_code=409, detail=str(e)) from e
        metrics.MODEL_VERSION.set(int(bundle.version[1:]))
        return {"loaded": bundle.version, "trainedAt": bundle.meta.get("trained_at")}

    @app.get("/metrics")
    def prometheus() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
