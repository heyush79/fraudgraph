from scorer.gen import scoring_pb2


def test_feature_vector_roundtrip():
    fv = scoring_pb2.FeatureVector(txn_id="t1", cnt_1m=9, sum_1h=1234.5, geo_speed_kmh=32223.5, in_cycle=True, channel=1)
    back = scoring_pb2.FeatureVector.FromString(fv.SerializeToString())
    assert back == fv
    assert back.cnt_5m == 0 and back.in_cycle is True and back.channel == 1


def test_score_result_roundtrip():
    r = scoring_pb2.ScoreResult(
        probability=0.91, model_version="v3",
        contributions=[scoring_pb2.Contribution(feature="cnt_1m", shap=0.31), scoring_pb2.Contribution(feature="in_cycle", shap=-0.02)],
    )
    back = scoring_pb2.ScoreResult.FromString(r.SerializeToString())
    assert back == r
    assert [c.feature for c in back.contributions] == ["cnt_1m", "in_cycle"]
