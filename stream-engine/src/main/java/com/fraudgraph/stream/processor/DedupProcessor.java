package com.fraudgraph.stream.processor;

import com.fraudgraph.stream.model.Transaction;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.apache.kafka.streams.processor.PunctuationType;
import org.apache.kafka.streams.processor.api.Processor;
import org.apache.kafka.streams.processor.api.ProcessorContext;
import org.apache.kafka.streams.processor.api.Record;
import org.apache.kafka.streams.state.KeyValueIterator;
import org.apache.kafka.streams.state.KeyValueStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/**
 * Drops any txnId already seen in the last TTL. State: {@code dedup-store} (txnId → firstSeenTs).
 * The stream is keyed by userId, so a given txnId always lands on the same partition and the
 * per-partition store is sufficient. A punctuator evicts entries older than the TTL.
 */
public final class DedupProcessor implements Processor<String, Transaction, String, Transaction> {
    private static final Logger log = LoggerFactory.getLogger(DedupProcessor.class);
    public static final String STORE = "dedup-store";

    private final Duration ttl;
    private final Duration evictEvery;
    private final Counter duplicates;
    private final Counter evicted;

    private ProcessorContext<String, Transaction> context;
    private KeyValueStore<String, Long> store;

    public DedupProcessor(Duration ttl, Duration evictEvery, MeterRegistry metrics) {
        this.ttl = ttl;
        this.evictEvery = evictEvery;
        this.duplicates = metrics.counter("fraudgraph_dedup_duplicates_total");
        this.evicted = metrics.counter("fraudgraph_dedup_evicted_total");
    }

    @Override
    public void init(ProcessorContext<String, Transaction> context) {
        this.context = context;
        this.store = context.getStateStore(STORE);
        context.schedule(evictEvery, PunctuationType.STREAM_TIME, this::evict);
    }

    @Override
    public void process(Record<String, Transaction> record) {
        Transaction txn = record.value();
        if (txn == null || txn.txnId() == null) {
            log.warn("dropping record without txnId, key={}", record.key());
            return;
        }
        if (store.get(txn.txnId()) != null) {
            duplicates.increment();
            log.debug("duplicate txn {} dropped", txn.txnId());
            return;
        }
        store.put(txn.txnId(), record.timestamp());
        context.forward(record);
    }

    private void evict(long streamTimeMs) {
        long cutoff = streamTimeMs - ttl.toMillis();
        List<String> expired = new ArrayList<>();
        try (KeyValueIterator<String, Long> it = store.all()) {
            while (it.hasNext()) {
                var kv = it.next();
                if (kv.value != null && kv.value < cutoff) {
                    expired.add(kv.key);
                }
            }
        }
        expired.forEach(store::delete);
        if (!expired.isEmpty()) {
            evicted.increment(expired.size());
            log.debug("evicted {} dedup entries older than {}", expired.size(), cutoff);
        }
    }
}
