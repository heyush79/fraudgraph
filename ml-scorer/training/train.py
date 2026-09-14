"""Train a scorer version from the engine's own feature log.

    python -m training.train --hours 24            # from Kafka, saves registry/vN, reloads scorer

Data source (LLD §4.3, amended in Phase 3): `fraud.decisions` carries the exact feature
vector the engine computed for EVERY transaction (windows, z-score, geo speed, graph), so it
is joined with `transactions.labels` on txnId. Recomputing those features from
`transactions.raw` in Python would mean a second implementation of the engine, which is the
train/serve skew the proto contract exists to prevent. The record timestamp on
fraud.decisions is the transaction's event time (Kafka Streams forwards it), which is what
the time-based split uses. The verdict on the decision is never a feature.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import xgboost as xgb

from scorer.features import FEATURES, matrix_from_decision_features, row_from_decision_features
from scorer.model import Registry, save_bundle

from . import evaluate
from .kafka_source import read_topic

log = logging.getLogger("train")

DECISIONS_TOPIC = "fraud.decisions"
LABELS_TOPIC = "transactions.labels"


# ---- data ---------------------------------------------------------------------

def build_frame(decisions: list[dict], labels: dict[str, str]) -> pd.DataFrame:
    """decisions: [{txnId, ts_ms, features}], labels: txnId -> pattern. Unlabelled = legit."""
    if not decisions:
        raise ValueError("no decisions to train on")
    X = matrix_from_decision_features([d["features"] for d in decisions])
    return _assemble([d["txnId"] for d in decisions], [d["ts_ms"] for d in decisions], X, labels)


def _assemble(txn_ids: list[str], ts_ms: list[int], X: np.ndarray, labels: dict[str, str]) -> pd.DataFrame:
    frame = pd.DataFrame(X, columns=list(FEATURES))
    frame.insert(0, "txn_id", txn_ids)
    frame.insert(1, "ts", pd.to_datetime(ts_ms, unit="ms", utc=True))
    frame["pattern"] = pd.array([labels.get(t) for t in txn_ids], dtype=object)
    frame["y"] = frame["pattern"].notna().astype(int)
    frame = frame.sort_values("ts", kind="stable").reset_index(drop=True)
    frame["pattern"] = frame["pattern"].astype(object).where(frame["pattern"].notna(), None)
    return frame


def time_split(frame: pd.DataFrame, test_fraction: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """First (1 − f) of the window trains, the last f tests. Never a random split: on
    temporal data that leaks the future into the past and overstates every metric."""
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be in (0, 1)")
    frame = frame.sort_values("ts", kind="stable").reset_index(drop=True)
    cut = int(len(frame) * (1 - test_fraction))
    return frame.iloc[:cut], frame.iloc[cut:]


def fit(train: pd.DataFrame, n_estimators: int = 200, max_depth: int = 6, seed: int = 42) -> xgb.XGBClassifier:
    y = train["y"].to_numpy()
    pos, neg = int(y.sum()), int(len(y) - y.sum())
    if pos == 0 or neg == 0:
        raise ValueError(f"need both classes to train; positives={pos} negatives={neg}")
    clf = xgb.XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=0.1,
        subsample=0.9,
        colsample_bytree=0.9,
        scale_pos_weight=neg / pos,      # fraud ≈ 1–2% of traffic: weight the minority class
        tree_method="hist",
        eval_metric="aucpr",
        n_jobs=4,
        random_state=seed,
    )
    clf.fit(train[list(FEATURES)], y)
    return clf


# ---- kafka --------------------------------------------------------------------

def load_from_kafka(bootstrap: str, hours: float, max_rows: int | None) -> tuple[pd.DataFrame, int]:
    """Streams fraud.decisions into compact rows (a million decisions as parsed dicts would be
    ~2 GB; as float tuples it is a few hundred MB), then joins the labels."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    txn_ids: list[str] = []
    ts_ms: list[int] = []
    rows: list[tuple[float, ...]] = []
    for n, msg in enumerate(read_topic(bootstrap, DECISIONS_TOPIC, since=since, max_rows=max_rows), 1):
        d = json.loads(msg.value)
        txn_ids.append(d["txnId"])
        ts_ms.append(msg.ts_ms)
        rows.append(tuple(row_from_decision_features(d["features"])))
        if n % 250_000 == 0:
            log.info("  %d decisions read", n)
    labels: dict[str, str] = {}
    # labels are keyed by txnId and stamped with the txn time; read a little earlier than the
    # decisions window so a label is never missed for a decision at its edge
    for msg in read_topic(bootstrap, LABELS_TOPIC, since=since - timedelta(hours=1)):
        lbl = json.loads(msg.value)
        if lbl.get("isFraud"):
            labels[lbl["txnId"]] = lbl.get("pattern", "UNKNOWN")
    if not rows:
        raise ValueError("no decisions in the window; is the demo running?")
    X = np.array(rows, dtype=np.float64)
    del rows
    return _assemble(txn_ids, ts_ms, X, labels), len(labels)


def git_sha() -> str | None:
    """From the environment when training runs in a container (the Makefile passes GIT_SHA), else from git."""
    if os.environ.get("GIT_SHA"):
        return os.environ["GIT_SHA"]
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        return None


# ---- pipeline -----------------------------------------------------------------

# A model trained on a handful of positives will happily report pr_auc 1.0 and suggest a
# threshold of 0.05. That happened on 2026-09-12: `make train` ran right after the host woke,
# the generator had (correctly) skipped ahead rather than backfilled, so "the last hour" held
# 22 seconds of traffic and 7 fraud labels. The toy model then served live decisions.
MIN_POSITIVES = 200
# The test slice has to contain enough fraud to mean anything. This is the check that
# matters; the wall-clock floor below is only there to catch a window so short that the
# traffic in it cannot be representative.
MIN_TEST_POSITIVES = 50
# Deliberately low. An earlier version used 30 minutes and rejected a perfectly good frame
# of 5,968 positives because throughput had been lower at the start of the window, so the
# last 20% of ROWS spanned only 20 minutes of clock. Row count is what the model sees;
# wall clock only guards against a window too brief to contain a daily pattern at all.
MIN_TEST_WINDOW_MINUTES = 10.0


def check_trainable(frame: pd.DataFrame, test_fraction: float) -> None:
    """Raises unless the frame can support an honest evaluation. Bypass with --force."""
    positives = int(frame["y"].sum())
    if positives < MIN_POSITIVES:
        raise ValueError(
            f"only {positives} fraud labels in the window (need {MIN_POSITIVES}); "
            f"widen --hours or let the demo run longer, or pass --force to register it anyway"
        )
    _, test = time_split(frame, test_fraction)
    test_positives = int(test["y"].sum())
    if test_positives < MIN_TEST_POSITIVES:
        raise ValueError(
            f"the test slice holds only {test_positives} fraud labels (need {MIN_TEST_POSITIVES}); "
            f"every metric from it would be noise. Widen --hours, or pass --force"
        )
    minutes = (test["ts"].iloc[-1] - test["ts"].iloc[0]).total_seconds() / 60
    if minutes < MIN_TEST_WINDOW_MINUTES:
        raise ValueError(
            f"test window is only {minutes:.1f} minutes (need {MIN_TEST_WINDOW_MINUTES}); "
            f"that is too brief to be representative. Widen --hours, or pass --force"
        )


def train_version(frame: pd.DataFrame, registry: Registry, version: str | None = None,
                  test_fraction: float = 0.2, n_estimators: int = 200, max_depth: int = 6,
                  force: bool = False) -> tuple[str, dict]:
    if not force:
        check_trainable(frame, test_fraction)
    version = version or registry.next_version()
    train, test = time_split(frame, test_fraction)
    clf = fit(train, n_estimators=n_estimators, max_depth=max_depth)
    p_test = clf.predict_proba(test[list(FEATURES)])[:, 1]
    y_test = test["y"].to_numpy()

    table = evaluate.sweep(y_test, p_test)
    suggested = evaluate.suggest_thresholds(table)
    review_thr = suggested["review"] if suggested["review"] is not None else 0.5
    per_pattern = evaluate.per_pattern_recall(y_test, p_test, test["pattern"].tolist(), review_thr)
    metrics = {**evaluate.summary_metrics(y_test, p_test)}

    booster = clf.get_booster()
    importance = booster.get_score(importance_type="gain")
    meta = {
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "features": list(FEATURES),
        "rows": int(len(frame)),
        "positives": int(frame["y"].sum()),
        "split": {
            "test_fraction": test_fraction,
            "train_rows": int(len(train)), "test_rows": int(len(test)),
            "train_from": frame["ts"].iloc[0].isoformat(), "train_to": train["ts"].iloc[-1].isoformat(),
            "test_from": test["ts"].iloc[0].isoformat(), "test_to": test["ts"].iloc[-1].isoformat(),
        },
        "params": {"n_estimators": n_estimators, "max_depth": max_depth, "scale_pos_weight": round(clf.get_params()["scale_pos_weight"], 3)},
        "metrics": metrics,
        "suggested_thresholds": suggested,
        "feature_importance_gain": {k: round(v, 3) for k, v in sorted(importance.items(), key=lambda kv: -kv[1])},
    }
    out = registry.path(version)
    save_bundle(booster, meta, out)
    (out / "metrics.json").write_text(json.dumps({"sweep": table, "per_pattern_recall": per_pattern}, indent=2))
    frame.to_parquet(out / "data.parquet", index=False)
    return version, meta


def reload_scorer(url: str, version: str) -> bool:
    import httpx
    try:
        r = httpx.post(url, params={"version": version}, timeout=30)
        r.raise_for_status()
        log.info("scorer reloaded: %s", r.json())
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("could not reload scorer at %s: %s (load it later with POST /reload?version=%s)", url, e, version)
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="train a FraudGraph scorer version from Kafka")
    ap.add_argument("--bootstrap-servers", default=os.environ.get("FRAUDGRAPH_BOOTSTRAP_SERVERS", "localhost:29092"))
    ap.add_argument("--hours", type=float, default=24.0, help="how far back to read fraud.decisions")
    ap.add_argument("--max-rows", type=int, default=None)
    ap.add_argument("--registry", default=os.environ.get("SCORER_REGISTRY", "registry"))
    ap.add_argument("--version", default=None, help="default: next vN")
    ap.add_argument("--test-fraction", type=float, default=0.2)
    ap.add_argument("--n-estimators", type=int, default=200)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--reload-url", default=os.environ.get("SCORER_RELOAD_URL", "http://localhost:8000/reload"))
    ap.add_argument("--no-reload", action="store_true")
    ap.add_argument("--force", action="store_true", help="register the version even if the window is too small to evaluate")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    frame, n_labels = load_from_kafka(args.bootstrap_servers, args.hours, args.max_rows)
    log.info("read %d decisions and %d fraud labels", len(frame), n_labels)
    log.info("frame: %d rows, %d positives (%.2f%%), %s .. %s", len(frame), frame["y"].sum(),
             100 * frame["y"].mean(), frame["ts"].iloc[0], frame["ts"].iloc[-1])

    version, meta = train_version(frame, Registry(pathlib.Path(args.registry)), args.version,
                                  args.test_fraction, args.n_estimators, args.max_depth, args.force)
    metrics_table = json.loads((Registry(pathlib.Path(args.registry)).path(version) / "metrics.json").read_text())
    print(f"\nmodel {version}: pr_auc={meta['metrics']['pr_auc']} roc_auc={meta['metrics']['roc_auc']} "
          f"train={meta['split']['train_rows']} test={meta['split']['test_rows']} positives={meta['positives']}")
    print(evaluate.format_table(metrics_table["sweep"]))
    print("per-pattern recall @", meta["suggested_thresholds"]["review"], metrics_table["per_pattern_recall"])
    print("suggested thresholds:", meta["suggested_thresholds"])
    print("feature importance (gain):", meta["feature_importance_gain"])
    if not args.no_reload:
        reload_scorer(args.reload_url, version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
