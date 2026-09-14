import json

import numpy as np
import pandas as pd
import pytest

from scorer.features import FEATURES
from training import evaluate
from training.train import build_frame, fit, time_split


def test_time_split_never_leaks_the_future(frame):
    train, test = time_split(frame, 0.2)
    assert len(train) + len(test) == len(frame)
    assert train["ts"].max() <= test["ts"].min()
    assert abs(len(test) / len(frame) - 0.2) < 0.01
    with pytest.raises(ValueError):
        time_split(frame, 1.0)


def test_build_frame_joins_labels_on_txn_id():
    decisions = [
        {"txnId": "a", "ts_ms": 2_000, "features": _feat(cnt1m=1)},
        {"txnId": "b", "ts_ms": 1_000, "features": _feat(cnt1m=12)},
    ]
    frame = build_frame(decisions, {"b": "VELOCITY"})
    assert frame["txn_id"].tolist() == ["b", "a"]            # sorted by event time
    assert frame["y"].tolist() == [1, 0]
    assert frame["pattern"].tolist() == ["VELOCITY", None]
    assert list(frame.columns[2:2 + len(FEATURES)]) == list(FEATURES)
    with pytest.raises(ValueError):
        build_frame([], {})


def test_tiny_window_is_refused_unless_forced(frame, tmp_path):
    """The v2 incident: 5,486 rows, 7 positives, a 22-second test window, pr_auc 1.0."""
    from scorer.model import Registry
    from training.train import check_trainable, train_version
    tiny = frame.head(400)
    with pytest.raises(ValueError, match="fraud labels"):
        check_trainable(tiny, 0.2)
    positives = frame[frame["y"] == 1]
    brief = pd.concat([positives, frame[frame["y"] == 0].head(len(positives))]).sort_values("ts")
    brief = brief.assign(ts=pd.date_range("2026-09-12", periods=len(brief), freq="1s", tz="UTC"))
    with pytest.raises(ValueError, match="test window"):
        check_trainable(brief, 0.2)   # enough positives, but only ~8 minutes of test data
    version, meta = train_version(brief, Registry(tmp_path), n_estimators=5, max_depth=2, force=True)
    assert version == "v1" and meta["positives"] == len(positives)


def test_fit_requires_both_classes(frame):
    with pytest.raises(ValueError, match="both classes"):
        fit(frame[frame["y"] == 0])


def test_registry_artifacts(registry):
    v = registry.path("v1")
    meta = json.loads((v / "meta.json").read_text())
    metrics = json.loads((v / "metrics.json").read_text())
    assert meta["version"] == "v1" and meta["features"] == list(FEATURES)
    assert meta["split"]["train_to"] <= meta["split"]["test_from"]
    assert meta["metrics"]["pr_auc"] > 0.8
    assert {r["threshold"] for r in metrics["sweep"]} >= {0.5, 0.85}
    assert set(metrics["per_pattern_recall"]) == {"GEO", "RING", "VELOCITY"}
    assert meta["suggested_thresholds"]["block"] is not None
    assert (v / "data.parquet").exists()
    assert len(pd.read_parquet(v / "data.parquet")) == meta["rows"]


def test_sweep_and_suggestions_on_a_toy_set():
    y = np.array([1, 1, 1, 0, 0, 0, 0, 0])
    p = np.array([0.9, 0.8, 0.3, 0.7, 0.2, 0.1, 0.05, 0.0])
    table = evaluate.sweep(y, p, thresholds=(0.25, 0.75))
    at25, at75 = table
    assert (at25["tp"], at25["fp"], at25["fn"]) == (3, 1, 0)
    assert at25["recall"] == 1.0 and at25["precision"] == 0.75
    assert (at75["tp"], at75["fp"], at75["fn"]) == (2, 0, 1)
    assert at75["precision"] == 1.0
    sugg = evaluate.suggest_thresholds(table, block_min_precision=0.98)
    assert sugg["block"] == 0.75
    assert sugg["review"] == 0.25
    assert evaluate.per_pattern_recall(y, p, ["GEO", "GEO", "RING", None, None, None, None, None], 0.75) == {
        "GEO": {"positives": 2, "recall": 1.0}, "RING": {"positives": 1, "recall": 0.0},
    }
    assert evaluate.summary_metrics(np.zeros(4), np.zeros(4)) == {"pr_auc": None, "roc_auc": None}


def _feat(**over):
    base = {"cnt1m": 1, "cnt5m": 1, "cnt1h": 1, "sum1h": 10.0, "amtZ": 0.0, "geoSpeedKmh": 0.0, "secsSinceLast": -1.0,
            "merchantRiskTier": 0, "nodeDegree": 0, "inCycle": False, "componentSize": 1, "channel": "CARD"}
    return {**base, **over}
