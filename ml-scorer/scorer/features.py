"""proto <-> numpy row. THE ONE PLACE feature order and encoding are defined.

Serving receives a FeatureVector proto from the stream engine. Training reads the
`features` map the same engine logged on fraud.decisions. Both go through this module,
and tests/test_features_parity.py asserts the two paths produce identical rows for the
same transaction. The feature list is derived from the proto descriptor, so adding a
field to scoring.proto without handling it here fails the test rather than silently
shifting columns.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .gen import scoring_pb2

# Ordered feature columns = every proto field except the identifier, in proto order.
FEATURES: tuple[str, ...] = tuple(
    f.name for f in scoring_pb2.FeatureVector.DESCRIPTOR.fields if f.name != "txn_id"
)

# channel enum as documented on the proto: CARD=0, UPI=1, P2P=2
CHANNELS: dict[str, int] = {"CARD": 0, "UPI": 1, "P2P": 2}


def _snake_to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


# proto field name -> key on the fraud.decisions `features` map (cnt_1m -> cnt1m, ...)
DECISION_KEYS: dict[str, str] = {f: _snake_to_camel(f) for f in FEATURES}


def row_from_proto(fv: scoring_pb2.FeatureVector) -> np.ndarray:
    """Serving path."""
    return np.array([float(getattr(fv, name)) for name in FEATURES], dtype=np.float64)


def row_from_decision_features(features: Mapping[str, Any]) -> np.ndarray:
    """Training path: the `features` object of one fraud.decisions event."""
    values: list[float] = []
    for name in FEATURES:
        key = DECISION_KEYS[name]
        if key not in features:
            raise KeyError(f"decision features missing {key!r} (proto field {name})")
        v = features[key]
        if name == "channel":
            v = CHANNELS[v] if isinstance(v, str) else v
        values.append(float(v))
    return np.array(values, dtype=np.float64)


def matrix_from_decision_features(rows: list[Mapping[str, Any]]) -> np.ndarray:
    if not rows:
        return np.empty((0, len(FEATURES)), dtype=np.float64)
    return np.vstack([row_from_decision_features(r) for r in rows])
