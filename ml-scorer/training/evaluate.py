"""Threshold sweep and per-pattern recall (LLD §4.3 step 4).

The decision thresholds in the stream engine's application.yml are chosen FROM this table,
which turns them from magic numbers into an artifact of an evaluation run.

    python -m training.evaluate --registry registry --version v1
"""
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Sequence

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

# 0.05 steps, plus the high end where auto-block thresholds live
DEFAULT_THRESHOLDS = tuple(round(t, 2) for t in np.arange(0.05, 1.0, 0.05)) + (0.97, 0.98, 0.99)


def sweep(y: np.ndarray, p: np.ndarray, thresholds: Sequence[float] = DEFAULT_THRESHOLDS) -> list[dict]:
    y = np.asarray(y).astype(bool)
    p = np.asarray(p)
    positives = int(y.sum())
    out = []
    for t in thresholds:
        flagged = p >= t
        tp = int((flagged & y).sum())
        fp = int((flagged & ~y).sum())
        fn = positives - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / positives if positives else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out.append({
            "threshold": float(t), "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
            "flagged_rate": round(float(flagged.mean()) if len(p) else 0.0, 5),
        })
    return out


def per_pattern_recall(y: np.ndarray, p: np.ndarray, patterns: Sequence[str | None], threshold: float) -> dict[str, dict]:
    y = np.asarray(y).astype(bool)
    p = np.asarray(p)
    pats = np.asarray([x if isinstance(x, str) and x else "" for x in patterns])
    result: dict[str, dict] = {}
    for pat in sorted({x for x in pats if x}):
        mask = (pats == pat) & y
        n = int(mask.sum())
        caught = int((p[mask] >= threshold).sum())
        result[pat] = {"positives": n, "recall": round(caught / n, 4) if n else 0.0}
    return result


def summary_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    y = np.asarray(y).astype(int)
    if y.sum() == 0 or y.sum() == len(y):
        return {"pr_auc": None, "roc_auc": None}
    return {
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
    }


def suggest_thresholds(table: list[dict], block_min_precision: float = 0.98, review_min_recall: float = 0.0) -> dict:
    """block = the lowest threshold whose precision clears block_min_precision (auto-blocking
    must be nearly always right); review = the threshold with the best F1. Both are
    suggestions for a human to confirm against the table."""
    block_rows = [r for r in table if r["precision"] >= block_min_precision and r["tp"] > 0]
    block = min(block_rows, key=lambda r: r["threshold"])["threshold"] if block_rows else None
    review = max(table, key=lambda r: (r["f1"], -r["threshold"]))["threshold"] if table else None
    if block is not None and review is not None and review >= block:
        review = round(block - 0.05, 2) if block > 0.05 else block
    return {"block": block, "review": review, "block_min_precision": block_min_precision}


def format_table(table: list[dict]) -> str:
    lines = [f"{'thr':>5} {'precision':>9} {'recall':>7} {'f1':>6} {'flagged':>8} {'tp':>7} {'fp':>7} {'fn':>7}"]
    for r in table:
        lines.append(f"{r['threshold']:>5.2f} {r['precision']:>9.3f} {r['recall']:>7.3f} {r['f1']:>6.3f} "
                     f"{r['flagged_rate']:>8.4f} {r['tp']:>7d} {r['fp']:>7d} {r['fn']:>7d}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="print the threshold sweep of a registry version")
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--version", default=None, help="default: latest")
    args = ap.parse_args(argv)
    from scorer.model import Registry
    reg = Registry(pathlib.Path(args.registry))
    version = args.version or reg.latest()
    if version is None:
        print("no versions in registry"); return 1
    metrics = json.loads((reg.path(version) / "metrics.json").read_text())
    meta = json.loads((reg.path(version) / "meta.json").read_text())
    print(f"model {version} trained {meta['trained_at']} rows={meta['rows']} positives={meta['positives']}")
    print(f"test window: {meta['split']['test_from']} .. {meta['split']['test_to']}  pr_auc={meta['metrics']['pr_auc']} roc_auc={meta['metrics']['roc_auc']}")
    print(format_table(metrics["sweep"]))
    print("per-pattern recall at review threshold", meta["suggested_thresholds"]["review"], ":", metrics["per_pattern_recall"])
    print("suggested thresholds:", meta["suggested_thresholds"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
