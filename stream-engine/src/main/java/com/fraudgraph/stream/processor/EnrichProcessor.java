package com.fraudgraph.stream.processor;

import com.fraudgraph.stream.model.EnrichedTransaction;
import com.fraudgraph.stream.model.Transaction;
import org.apache.kafka.streams.processor.api.ContextualProcessor;
import org.apache.kafka.streams.processor.api.Record;

import java.util.Map;

/**
 * Attaches static lookups to the transaction. Phase 1: merchant risk tier and the ingest
 * timestamp for latency accounting. Phase 2 adds reads of profile-store and last-location-store.
 */
public final class EnrichProcessor extends ContextualProcessor<String, Transaction, String, EnrichedTransaction> {
    private final Map<String, Integer> merchantRiskTiers;

    public EnrichProcessor(Map<String, Integer> merchantRiskTiers) {
        this.merchantRiskTiers = merchantRiskTiers == null ? Map.of() : Map.copyOf(merchantRiskTiers);
    }

    @Override
    public void process(Record<String, Transaction> record) {
        Transaction txn = record.value();
        int tier = merchantRiskTiers.getOrDefault(txn.merchantCategory(), 0);
        context().forward(record.withValue(new EnrichedTransaction(txn, tier, System.nanoTime())));
    }
}
