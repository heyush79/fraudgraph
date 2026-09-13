"""Prometheus metrics for the scorer (LLD §4.4: score histogram, latency, model version)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

REQUESTS = Counter("scorer_requests_total", "Score RPCs", ["outcome"])
LATENCY = Histogram(
    "scorer_latency_seconds", "Score RPC latency",
    buckets=(0.001, 0.002, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.5),
)
SCORE = Histogram("scorer_score", "Fraud probability distribution", buckets=[i / 20 for i in range(1, 21)])
MODEL_VERSION = Gauge("scorer_model_version", "Loaded model version number (0 = none)")
