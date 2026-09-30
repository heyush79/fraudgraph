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


def _variant(registry, tmp_path, name: str, features: list[str]):
    meta = json.loads((registry.path("v1") / "meta.json").read_text())
    meta["features"] = features
    meta["version"] = name
    d = tmp_path / name; d.mkdir()
    (d / "model.json").write_bytes((registry.path("v1") / "model.json").read_bytes())
    (d / "meta.json").write_text(json.dumps(meta))
    return d


def test_a_model_needing_a_feature_this_build_does_not_produce_is_refused(registry, tmp_path):
    bad = _variant(registry, tmp_path, "v9", list(FEATURES[:-1]) + ["feature_from_the_future"])
    with pytest.raises(ValueError, match="does not produce"):
        ModelBundle.load(bad)


def test_a_model_trained_before_a_feature_was_added_scores_on_the_columns_it_knows(registry, frame, tmp_path):
    """After pass-through landed in the proto, v2 (12 features) had to keep serving while v3
    trained. It must be scored on ITS columns, picked by name, not on the first 12 positions."""
    old_features = [f for f in FEATURES if f not in ("pass_through_ratio", "secs_since_inbound", "chain_depth")]
    train_frame = frame.copy()
    from training.train import fit
    clf = fit(train_frame, n_estimators=30, max_depth=3, features=tuple(old_features))
    d = tmp_path / "v2"; d.mkdir()
    clf.get_booster().save_model(str(d / "model.json"))
    (d / "meta.json").write_text(json.dumps({"version": "v2", "features": old_features}))

    bundle = ModelBundle.load(d)
    assert bundle.unused == ["pass_through_ratio", "secs_since_inbound", "chain_depth"]
    row = frame[frame["pattern"] == "GEO"].iloc[0]
    full = row[list(FEATURES)].to_numpy(dtype=float)
    p = bundle.predict(full)
    expected = clf.predict_proba(row[old_features].to_frame().T.astype(float))[0, 1]
    assert p.probability == pytest.approx(expected, rel=1e-5)
    assert all(f in old_features for f, _ in p.contributions)
    # the served-but-unknown features cannot move its score
    tampered = full.copy()
    for f in bundle.unused:
        tampered[FEATURES.index(f)] = 12345.0
    assert bundle.predict(tampered).probability == pytest.approx(p.probability)


def test_holder_swaps_and_reports_missing(registry):
    holder = ModelHolder(registry)
    assert holder.current is None
    assert holder.load().version == "v1"
    with pytest.raises(FileNotFoundError, match="unknown model version"):
        holder.load("v7")
    assert holder.current.version == "v1"
    assert ModelHolder(Registry(registry.root / "empty")).try_load_latest() is None


def test_an_unservable_newest_version_is_skipped_not_fatal(registry, tmp_path):
    """A model needing a feature this build lacks (a rollback of the proto) must not stop the
    scorer starting: it serves the newest servable version, or none."""
    import shutil
    reg = Registry(tmp_path / "reg")
    shutil.copytree(registry.path("v1"), reg.path("v1"))
    shutil.copytree(registry.path("v1"), reg.path("v2"))
    meta = json.loads((reg.path("v2") / "meta.json").read_text())
    meta["features"] = meta["features"] + ["feature_from_the_future"]
    meta["version"] = "v2"
    (reg.path("v2") / "meta.json").write_text(json.dumps(meta))

    holder = ModelHolder(reg)
    bundle = holder.try_load_latest()
    assert bundle is not None and bundle.version == "v1"
    assert "v2" in holder.incompatible and "does not produce" in holder.incompatible["v2"]


def test_no_servable_version_means_no_model_rather_than_a_crash(registry, tmp_path):
    import shutil
    reg = Registry(tmp_path / "only-stale")
    shutil.copytree(registry.path("v1"), reg.path("v1"))
    meta = json.loads((reg.path("v1") / "meta.json").read_text())
    meta["features"] = ["feature_from_the_future"]
    (reg.path("v1") / "meta.json").write_text(json.dumps(meta))
    holder = ModelHolder(reg)
    assert holder.try_load_latest() is None
    assert list(holder.incompatible) == ["v1"]


def test_an_ablation_trains_without_the_excluded_features(frame, tmp_path):
    from training.train import train_version
    reg = Registry(tmp_path / "abl")
    version, meta = train_version(frame, reg, exclude=("chain_depth",), n_estimators=20, max_depth=3, force=True)
    assert "chain_depth" not in meta["features"] and meta["excludedFeatures"] == ["chain_depth"]
    assert ModelBundle.load(reg.path(version)).unused == ["chain_depth"]
    with pytest.raises(ValueError, match="unknown features"):
        train_version(frame, reg, exclude=("nope",), force=True)
