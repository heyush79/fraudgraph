import grpc
import pytest
from fastapi.testclient import TestClient

from api.admin import create_app
from scorer.features import FEATURES
from scorer.gen import scoring_pb2, scoring_pb2_grpc
from scorer.model import ModelHolder
from scorer.server import build_grpc_server
from scorer.settings import Settings


def _vector(row, txn="t-1") -> scoring_pb2.FeatureVector:
    kwargs = {name: (bool(v) if name == "in_cycle" else (int(v) if name in ("cnt_1m", "cnt_5m", "cnt_1h", "merchant_risk_tier", "node_degree", "component_size", "channel") else float(v)))
              for name, v in zip(FEATURES, row)}
    return scoring_pb2.FeatureVector(txn_id=txn, **kwargs)


@pytest.mark.asyncio
async def test_grpc_scores_and_fails_precondition_without_model(registry, frame):
    holder = ModelHolder(registry)
    settings = Settings(shap_min_probability=0.0, workers=2)
    server, port = await build_grpc_server(holder, settings, port=0)
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
            stub = scoring_pb2_grpc.ScoringServiceStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as err:
                await stub.Score(_vector(frame.iloc[0][list(FEATURES)].to_numpy(dtype=float)))
            assert err.value.code() == grpc.StatusCode.FAILED_PRECONDITION

            holder.load("v1")
            geo = frame[frame["pattern"] == "GEO"].iloc[0]
            res = await stub.Score(_vector(geo[list(FEATURES)].to_numpy(dtype=float)), timeout=2)
            assert res.model_version == "v1"
            assert res.probability > 0.5
            assert len(res.contributions) == 5
            assert res.contributions[0].feature == "geo_speed_kmh"
    finally:
        await server.stop(0)


def test_admin_endpoints(registry):
    holder = ModelHolder(registry)
    client = TestClient(create_app(holder))
    assert client.get("/health").json() == {"status": "NO_MODEL", "modelVersion": None, "available": ["v1"]}
    assert client.get("/model").status_code == 404
    assert client.post("/reload").json()["loaded"] == "v1"
    assert client.get("/health").json()["status"] == "UP"
    assert client.get("/model").json()["features"] == list(FEATURES)
    assert client.post("/reload", params={"version": "v9"}).status_code == 404
    assert client.post("/reload", params={"version": "nope"}).status_code == 422
    assert b"scorer_model_version 1.0" in client.get("/metrics").content
