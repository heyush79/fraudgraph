"""Event schemas for `transactions.raw` and `transactions.labels` (LLD §2.1)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class Channel(str, Enum):
    CARD = "CARD"
    UPI = "UPI"
    P2P = "P2P"


class FraudPattern(str, Enum):
    VELOCITY = "VELOCITY"
    RING = "RING"
    GEO = "GEO"


def iso_ts(ts: datetime) -> str:
    """ISO-8601 with millisecond precision and a trailing Z, e.g. 2026-09-04T10:15:03.120Z."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


@dataclass(frozen=True, slots=True)
class Transaction:
    txn_id: str
    user_id: str
    merchant_id: str
    counterparty_id: str | None
    amount: float
    currency: str
    lat: float
    lon: float
    device_id: str
    channel: Channel
    ts: datetime

    def to_json(self) -> str:
        return json.dumps(
            {
                "txnId": self.txn_id,
                "userId": self.user_id,
                "merchantId": self.merchant_id,
                "counterpartyId": self.counterparty_id,
                "amount": round(self.amount, 2),
                "currency": self.currency,
                "lat": round(self.lat, 6),
                "lon": round(self.lon, 6),
                "deviceId": self.device_id,
                "channel": self.channel.value,
                "ts": iso_ts(self.ts),
            },
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class Label:
    """Ground truth for one injected transaction. Only fraud is labelled;
    a txnId absent from `transactions.labels` is legitimate."""

    txn_id: str
    user_id: str
    pattern: FraudPattern
    episode_id: str
    ts: datetime
    # Position within a multi-step episode, when the injector knows it. For a ring, hop 0 is the
    # origin and hop == hops-1 is the transfer that closes the cycle. Lets recall be measured by
    # position exactly, instead of inferring completeness from timing.
    hop: int | None = None
    hops: int | None = None
    # "scenario" for episodes a person triggered for a demo (generator.scenario), so recall
    # measurements can leave out fraud that was planted to be watched rather than found.
    source: str | None = None

    def to_json(self) -> str:
        doc = {
            "txnId": self.txn_id,
            "userId": self.user_id,
            "isFraud": True,
            "pattern": self.pattern.value,
            "episodeId": self.episode_id,
            "ts": iso_ts(self.ts),
        }
        if self.hop is not None:
            doc["hop"] = self.hop
            doc["hops"] = self.hops
        if self.source is not None:
            doc["source"] = self.source
        return json.dumps(doc, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ScheduledTxn:
    """A transaction to publish at wall-clock time `at`, with its optional label."""

    at: datetime
    txn: Transaction
    label: Label | None = None

    def __lt__(self, other: "ScheduledTxn") -> bool:  # heapq ordering
        return self.at < other.at

