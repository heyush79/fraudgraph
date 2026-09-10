import json

from generator.models import Channel, FraudPattern, Label, Transaction, iso_ts


def test_iso_ts_has_millis_and_z(t0):
    assert iso_ts(t0) == "2026-09-04T10:15:03.120Z"


def test_transaction_json_matches_lld_schema(t0):
    txn = Transaction(
        txn_id="x", user_id="u_10023", merchant_id="m_ELEC_0042", counterparty_id=None,
        amount=1499.004, currency="INR", lat=17.3850, lon=78.4867, device_id="d_ab12",
        channel=Channel.CARD, ts=t0,
    )
    doc = json.loads(txn.to_json())
    assert set(doc) == {"txnId", "userId", "merchantId", "counterpartyId", "amount", "currency", "lat", "lon", "deviceId", "channel", "ts"}
    assert doc["amount"] == 1499.0
    assert doc["counterpartyId"] is None
    assert doc["channel"] == "CARD"
    assert doc["ts"] == "2026-09-04T10:15:03.120Z"


def test_label_json(t0):
    doc = json.loads(Label("x", "u_1", FraudPattern.VELOCITY, "ep_1", t0).to_json())
    assert doc == {"txnId": "x", "userId": "u_1", "isFraud": True, "pattern": "VELOCITY", "episodeId": "ep_1", "ts": "2026-09-04T10:15:03.120Z"}
