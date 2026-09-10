"""Publishers for `transactions.raw` (key = userId) and `transactions.labels` (key = txnId)."""
from __future__ import annotations

import logging
import sys
from typing import Protocol

from .models import Label, Transaction

log = logging.getLogger(__name__)

RAW_TOPIC = "transactions.raw"
LABELS_TOPIC = "transactions.labels"


class Publisher(Protocol):
    def publish_txn(self, txn: Transaction) -> None: ...
    def publish_label(self, label: Label) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


class InMemoryPublisher:
    """Test double: records everything in order."""

    def __init__(self) -> None:
        self.txns: list[Transaction] = []
        self.labels: list[Label] = []

    def publish_txn(self, txn: Transaction) -> None:
        self.txns.append(txn)

    def publish_label(self, label: Label) -> None:
        self.labels.append(label)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class StdoutPublisher:
    """`--dry-run`: one JSON line per event, prefixed with the topic."""

    def publish_txn(self, txn: Transaction) -> None:
        sys.stdout.write(f"{RAW_TOPIC}\t{txn.user_id}\t{txn.to_json()}\n")

    def publish_label(self, label: Label) -> None:
        sys.stdout.write(f"{LABELS_TOPIC}\t{label.txn_id}\t{label.to_json()}\n")

    def flush(self) -> None:
        sys.stdout.flush()

    def close(self) -> None:
        sys.stdout.flush()


class KafkaPublisher:
    def __init__(self, bootstrap_servers: str, client_id: str = "fraudgraph-generator") -> None:
        from confluent_kafka import Producer  # imported lazily so tests never need librdkafka

        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "client.id": client_id,
                # Idempotent + acks=all: no duplicates from producer retries, so the
                # dedup store in the stream engine only has to cover consumer redelivery.
                "enable.idempotence": True,
                "acks": "all",
                "linger.ms": 5,
                "batch.num.messages": 10_000,
                "compression.type": "lz4",
            }
        )
        self._errors = 0

    def _on_delivery(self, err, msg) -> None:  # type: ignore[no-untyped-def]
        if err is not None:
            self._errors += 1
            if self._errors <= 10 or self._errors % 1000 == 0:
                log.error("delivery failed topic=%s key=%s err=%s", msg.topic(), msg.key(), err)

    def publish_txn(self, txn: Transaction) -> None:
        self._produce(RAW_TOPIC, txn.user_id, txn.to_json())

    def publish_label(self, label: Label) -> None:
        self._produce(LABELS_TOPIC, label.txn_id, label.to_json())

    def _produce(self, topic: str, key: str, value: str) -> None:
        from confluent_kafka import KafkaException

        while True:
            try:
                self._producer.produce(topic, key=key.encode(), value=value.encode(), on_delivery=self._on_delivery)
                break
            except BufferError:
                # local queue full at very high tps: serve callbacks, then retry
                self._producer.poll(0.01)
            except KafkaException as e:  # pragma: no cover - broker-side failure
                log.error("produce failed topic=%s key=%s err=%s", topic, key, e)
                break
        self._producer.poll(0)

    def flush(self) -> None:
        self._producer.flush(10)

    def close(self) -> None:
        remaining = self._producer.flush(30)
        if remaining:
            log.warning("%d messages still undelivered at close", remaining)
        if self._errors:
            log.warning("%d delivery errors in total", self._errors)
