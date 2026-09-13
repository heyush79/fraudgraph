"""Bounded topic reads for training: seek to a timestamp, read to the high watermark, stop."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Iterator, NamedTuple

log = logging.getLogger(__name__)


class Message(NamedTuple):
    key: str | None
    value: bytes
    ts_ms: int


def read_topic(bootstrap_servers: str, topic: str, since: datetime | None = None,
               max_rows: int | None = None, idle_timeout_s: float = 10.0) -> Iterator[Message]:
    from confluent_kafka import Consumer, TopicPartition

    consumer = Consumer({
        "bootstrap.servers": bootstrap_servers,
        "group.id": f"fraudgraph-trainer-{uuid.uuid4().hex[:8]}",
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
        "fetch.max.bytes": 50 * 1024 * 1024,
    })
    try:
        md = consumer.list_topics(topic, timeout=10)
        if topic not in md.topics or md.topics[topic].error is not None:
            raise RuntimeError(f"topic {topic} not found")
        parts = [TopicPartition(topic, p) for p in md.topics[topic].partitions]

        # end offsets captured now: read up to here and no further
        high = {tp.partition: consumer.get_watermark_offsets(tp, timeout=10)[1] for tp in parts}
        if since is not None:
            since_ms = int(since.timestamp() * 1000)
            probes = [TopicPartition(topic, tp.partition, since_ms) for tp in parts]
            starts = consumer.offsets_for_times(probes, timeout=10)
        else:
            starts = [TopicPartition(topic, tp.partition, consumer.get_watermark_offsets(tp, timeout=10)[0]) for tp in parts]

        assign = []
        for tp in starts:
            offset = tp.offset if tp.offset >= 0 else high[tp.partition]  # -1: nothing after `since`
            assign.append(TopicPartition(topic, tp.partition, offset))
        pending = {tp.partition for tp in assign if tp.offset < high[tp.partition]}
        consumer.assign(assign)
        log.info("reading %s: %d partitions, %d messages to the watermark", topic,
                 len(parts), sum(high[tp.partition] - tp.offset for tp in assign))

        produced = 0
        idle = 0.0
        while pending and (max_rows is None or produced < max_rows):
            msg = consumer.poll(1.0)
            if msg is None:
                idle += 1.0
                if idle >= idle_timeout_s:
                    log.warning("idle for %.0fs with partitions %s pending; stopping", idle, sorted(pending))
                    break
                continue
            idle = 0.0
            if msg.error():
                log.warning("consumer error: %s", msg.error())
                continue
            if msg.offset() + 1 >= high[msg.partition()]:
                pending.discard(msg.partition())
            key = msg.key().decode() if msg.key() else None
            yield Message(key, msg.value(), msg.timestamp()[1])
            produced += 1
    finally:
        consumer.close()
