"""THE feature-parity test (LLD §10): the serving path (proto) and the training path
(fraud.decisions features map) must produce identical vectors for the same transaction.
Never delete this test."""
import numpy as np
import pytest

from scorer.features import CHANNELS, DECISION_KEYS, FEATURES, matrix_from_decision_features, row_from_decision_features, row_from_proto
from scorer.gen import scoring_pb2

# what the stream engine logs on fraud.decisions for one transaction (camelCase, channel as text)
DECISION_FEATURES = {
    "cnt1m": 4, "cnt5m": 22, "cnt1h": 71, "sum1h": 24291.6, "amtZ": 3.8, "geoSpeedKmh": 79.4,
    "secsSinceLast": 126.7, "merchantRiskTier": 1, "nodeDegree": 2, "inCycle": True, "componentSize": 10, "channel": "P2P",
}
# what the same engine sends to the scorer over gRPC for that transaction
PROTO_VECTOR = scoring_pb2.FeatureVector(
    txn_id="a5e82a27", cnt_1m=4, cnt_5m=22, cnt_1h=71, sum_1h=24291.6, amt_z=3.8, geo_speed_kmh=79.4,
    secs_since_last=126.7, merchant_risk_tier=1, node_degree=2, in_cycle=True, component_size=10, channel=2,
)


def test_train_and_serve_rows_are_identical():
    serve = row_from_proto(PROTO_VECTOR)
    train = row_from_decision_features(DECISION_FEATURES)
    np.testing.assert_array_equal(serve, train)
    assert serve.dtype == train.dtype == np.float64
    assert serve.shape == (len(FEATURES),)


def test_feature_list_is_the_proto_minus_txn_id():
    proto_fields = [f.name for f in scoring_pb2.FeatureVector.DESCRIPTOR.fields]
    assert proto_fields[0] == "txn_id"
    assert list(FEATURES) == proto_fields[1:]
    assert len(FEATURES) == 12


def test_decision_keys_cover_every_feature_and_match_engine_naming():
    assert set(DECISION_KEYS) == set(FEATURES)
    assert DECISION_KEYS["cnt_1m"] == "cnt1m"
    assert DECISION_KEYS["geo_speed_kmh"] == "geoSpeedKmh"
    assert DECISION_KEYS["merchant_risk_tier"] == "merchantRiskTier"
    assert set(DECISION_KEYS.values()) == set(DECISION_FEATURES)


def test_channel_encoding_matches_proto_comment():
    assert CHANNELS == {"CARD": 0, "UPI": 1, "P2P": 2}
    for name, code in CHANNELS.items():
        assert row_from_decision_features({**DECISION_FEATURES, "channel": name})[-1] == code


def test_missing_feature_fails_loudly():
    broken = dict(DECISION_FEATURES); del broken["amtZ"]
    with pytest.raises(KeyError, match="amtZ"):
        row_from_decision_features(broken)


def test_matrix_stacks_rows():
    m = matrix_from_decision_features([DECISION_FEATURES, {**DECISION_FEATURES, "cnt1m": 9}])
    assert m.shape == (2, len(FEATURES))
    assert m[1, 0] == 9
    assert matrix_from_decision_features([]).shape == (0, len(FEATURES))
