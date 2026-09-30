"""ModelBundle: an XGBoost booster + its metadata, and the on-disk registry.

Registry layout (LLD §4.2):
    registry/
      v1/model.json      xgboost native JSON
      v1/meta.json       version, trained_at, features, metrics, git sha, thresholds
      v1/metrics.json    threshold sweep table
      v1/data.parquet    the training frame, for reproducibility

Explanations are TreeSHAP values computed by XGBoost itself (`pred_contribs=True`), the same
algorithm shap.TreeExplainer runs for tree models, without pulling numba/llvmlite into the
serving image. Values are in log-odds space; the top-5 by magnitude are returned.
"""
from __future__ import annotations

import json
import pathlib
import re
import threading
from dataclasses import dataclass
from typing import Any

import logging

import numpy as np
import xgboost as xgb

from .features import FEATURES

log = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"^v(\d+)$")


@dataclass(frozen=True, slots=True)
class Prediction:
    probability: float
    contributions: list[tuple[str, float]]   # (feature, shap), top-5 by |shap|
    model_version: str


class ModelBundle:
    """A model is served by name, not by position. It scores the columns it was trained on,
    picked out of the vector this build produces, so adding a feature to scoring.proto does
    not strand every existing model: the old one keeps serving on the features it knows
    while a new one trains. Only a model that needs a feature this build does NOT produce
    (a rollback) is refused, because scoring it would mean inventing a column."""

    def __init__(self, booster: xgb.Booster, meta: dict[str, Any]) -> None:
        trained = list(meta.get("features") or [])
        missing = [f for f in trained if f not in FEATURES]
        if not trained or missing or len(set(trained)) != len(trained):
            raise ValueError(
                f"model {meta.get('version')} needs features this build does not produce: "
                f"{missing or trained}; serving produces {list(FEATURES)}"
            )
        self.booster = booster
        self.meta = meta
        self.version: str = meta["version"]
        self.features: list[str] = trained
        self._columns = np.array([FEATURES.index(f) for f in trained], dtype=np.intp)
        # served but not scored by this model; reported by /health so the gap is visible
        self.unused: list[str] = [f for f in FEATURES if f not in trained]

    @classmethod
    def load(cls, version_dir: pathlib.Path) -> "ModelBundle":
        booster = xgb.Booster()
        booster.load_model(str(version_dir / "model.json"))
        meta = json.loads((version_dir / "meta.json").read_text())
        return cls(booster, meta)

    def predict(self, row: np.ndarray, explain_min_probability: float = 0.0, top_k: int = 5) -> Prediction:
        """`row` is the full served vector, in FEATURES order."""
        dm = xgb.DMatrix(row[self._columns].reshape(1, -1), feature_names=self.features)
        probability = float(self.booster.predict(dm)[0])
        contributions: list[tuple[str, float]] = []
        if probability >= explain_min_probability:
            contribs = self.booster.predict(dm, pred_contribs=True)[0][:-1]  # last column is the bias term
            order = np.argsort(-np.abs(contribs))[:top_k]
            contributions = [(self.features[i], float(contribs[i])) for i in order]
        return Prediction(probability, contributions, self.version)


def save_bundle(booster: xgb.Booster, meta: dict[str, Any], version_dir: pathlib.Path) -> None:
    version_dir.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(version_dir / "model.json"))
    (version_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))


class Registry:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = pathlib.Path(root)

    def versions(self) -> list[str]:
        if not self.root.exists():
            return []
        found = []
        for d in self.root.iterdir():
            m = _VERSION_RE.match(d.name)
            if m and (d / "model.json").exists() and (d / "meta.json").exists():
                found.append((int(m.group(1)), d.name))
        return [name for _, name in sorted(found)]

    def latest(self) -> str | None:
        v = self.versions()
        return v[-1] if v else None

    def next_version(self) -> str:
        v = self.versions()
        return f"v{int(v[-1][1:]) + 1}" if v else "v1"

    def path(self, version: str) -> pathlib.Path:
        return self.root / version


class ModelHolder:
    """The currently served bundle; swapped atomically by /reload."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._lock = threading.Lock()
        self.current: ModelBundle | None = None
        # version -> why it cannot be served by this build (a feature-list mismatch)
        self.incompatible: dict[str, str] = {}

    def load(self, version: str | None = None) -> ModelBundle:
        version = version or self.registry.latest()
        if version is None:
            raise FileNotFoundError(f"no model versions in {self.registry.root}")
        if version not in self.registry.versions():
            raise FileNotFoundError(f"unknown model version {version}; have {self.registry.versions()}")
        bundle = ModelBundle.load(self.registry.path(version))
        with self._lock:
            self.current = bundle
        return bundle

    def try_load_latest(self) -> ModelBundle | None:
        """The newest version this build can serve, or None.

        A model trained before a feature was added to scoring.proto is still servable (see
        ModelBundle). One that needs a feature this build does not produce is not, and refusing
        to start over it would take the scorer down for as long as a retrain takes; skipping it
        lets the engine run DEGRADED behind its breaker until a servable version lands, which is
        the failure mode the whole design is built around.
        """
        self.incompatible = {}
        for version in reversed(self.registry.versions()):
            try:
                return self.load(version)
            except ValueError as e:
                self.incompatible[version] = str(e)
                log.warning("skipping model %s: %s", version, e)
            except FileNotFoundError:
                continue
        return None
