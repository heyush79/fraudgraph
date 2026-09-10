package com.fraudgraph.stream.config;

import com.fraudgraph.stream.model.Transaction;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.streams.processor.TimestampExtractor;

/**
 * Event time = the transaction's own {@code ts}, so velocity windows and dedup TTLs are
 * computed on when the payment happened, not when the engine got around to it (replays
 * of transactions.raw then reproduce the same decisions). Falls back to the record time.
 */
public final class TransactionTimestampExtractor implements TimestampExtractor {
    @Override
    public long extract(ConsumerRecord<Object, Object> record, long partitionTime) {
        if (record.value() instanceof Transaction txn && txn.ts() != null) {
            return txn.ts().toEpochMilli();
        }
        return record.timestamp() >= 0 ? record.timestamp() : partitionTime;
    }
}
