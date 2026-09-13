import json

import numpy as np
import pytest

from scorer.features import FEATURES
from scorer.model import ModelBundle, ModelHolder, Registry


def test_registry_versions_and_next(registry):
    assert registry.versions() == ["v1"]
    assert registry.latest() == "v1"
    assert registry.next_version() == "v2"
    assert Registry(registry.root / "missing").latest() is None


def test_bundle_predicts_and_explains(registry, frame):
    bundle = ModelBundle.load(registry.path("v1"))
    geo = frame[frame["pattern"] == "GEO"].iloc[0]
    legit = frame[frame["y"] == 0].iloc[0]
    hot = bundle.predict(geo[list(FEATURES)].to_numpy(dtype=float))
    cold = bundle.predict(legit[list(FEATURES)].to_numpy(dtype=float))
    assert 0.0 <= cold.probability < 0.5 < hot.probability <= 1.0
    assert hot.model_version == "v1"
    assert len(hot.contributions) == 5
    mags = [abs(s) for _, s in hot.contributions]
    assert mags == sorted(mags, reverse=True)
    assert hot.contributions[0][0] == "geo_speed_kmh"
    assert all(f in FEATURES for f, _ in hot.contributions)


def test_explanations_skipped_below_threshold(registry, frame):
    bundle = ModelBundle.load(registry.path("v1"))
    legit = frame[frame["y"] == 0].iloc[0]
    p = bundle.predict(legit[list(FEATURES)].to_numpy(dtype=float), explain_min_probability=0.4)
    assert p.contributions == []


def test_bundle_rejects_feature_drift(registry, tmp_path):
    meta = json.loads((registry.path("v1") / "meta.json").read_text())
    meta["features"] = meta["features"][:-1]
    bad = tmp_path / "v9"; bad.mkdir()
    (bad / "model.json").write_bytes((registry.path("v1") / "model.json").read_bytes())
    (bad / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="serving expects"):
        ModelBundle.load(bad)


def test_holder_swaps_and_reports_missing(registry):
    holder = ModelHolder(registry)
    assert holder.current is None
    assert holder.load().version == "v1"
    with pytest.raises(FileNotFoundError, match="unknown model version"):
        holder.load("v7")
    assert holder.current.version == "v1"
    assert ModelHolder(Registry(registry.root / "empty")).try_load_latest() is None
