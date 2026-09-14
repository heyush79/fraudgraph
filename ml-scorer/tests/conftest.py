import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.gen_proto import generate  # noqa: E402

if not (ROOT / "scorer" / "gen" / "scoring_pb2.py").exists():
    generate()

from scorer.features import FEATURES  # noqa: E402
from scorer.model import Registry  # noqa: E402
from training.train import train_version  # noqa: E402


def synthetic_frame(n: int = 8000, seed: int = 0) -> pd.DataFrame:
    """Legit traffic plus three planted patterns that mirror the generator's injectors."""
    rng = np.random.default_rng(seed)
    X = pd.DataFrame({
        "cnt_1m": rng.integers(1, 4, n), "cnt_5m": rng.integers(1, 8, n), "cnt_1h": rng.integers(1, 20, n),
        "sum_1h": rng.lognormal(8, 0.8, n), "amt_z": rng.normal(0, 1, n), "geo_speed_kmh": rng.uniform(0, 80, n),
        "secs_since_last": rng.uniform(60, 3600, n), "merchant_risk_tier": rng.integers(0, 2, n),
        "node_degree": rng.integers(0, 3, n), "in_cycle": np.zeros(n), "component_size": rng.integers(1, 4, n),
        "channel": rng.integers(0, 2, n),
    })
    pattern = np.array([None] * n, dtype=object)
    idx = rng.choice(n, size=int(n * 0.05), replace=False)
    third = len(idx) // 3
    X.loc[idx[:third], "cnt_1m"] = rng.integers(9, 30, third); pattern[idx[:third]] = "VELOCITY"
    X.loc[idx[third:2 * third], "geo_speed_kmh"] = rng.uniform(1500, 30000, third); pattern[idx[third:2 * third]] = "GEO"
    rest = idx[2 * third:]
    X.loc[rest, "in_cycle"] = 1; X.loc[rest, "channel"] = 2; X.loc[rest, "component_size"] = 5; pattern[rest] = "RING"
    frame = X[list(FEATURES)].astype(float)
    frame.insert(0, "txn_id", [f"t{i}" for i in range(n)])
    frame.insert(1, "ts", pd.date_range("2026-09-01", periods=n, freq="20s", tz="UTC"))
    frame["pattern"] = pattern
    frame["y"] = frame["pattern"].notna().astype(int)
    return frame


@pytest.fixture(scope="session")
def frame() -> pd.DataFrame:
    return synthetic_frame()


@pytest.fixture(scope="session")
def registry(tmp_path_factory, frame) -> Registry:
    reg = Registry(tmp_path_factory.mktemp("registry"))
    train_version(frame, reg, n_estimators=40, max_depth=4)
    return reg
