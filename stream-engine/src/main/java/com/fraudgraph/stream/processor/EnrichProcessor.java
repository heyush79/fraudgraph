package com.fraudgraph.stream.processor;

import com.fraudgraph.stream.model.EnrichedTransaction;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.profile.LastLocation;
import com.fraudgraph.stream.profile.WelfordAccumulator;
import org.apache.kafka.streams.processor.api.Processor;
import org.apache.kafka.streams.processor.api.ProcessorContext;
import org.apache.kafka.streams.processor.api.Record;
import org.apache.kafka.streams.state.KeyValueStore;

import java.util.Map;

/**
 * LLD §3.1: reads profile-store and last-location-store (the CheckProcessor writes them)
 * and attaches the static merchant risk tier. Reads happen here, before the current txn
 * touches state, so every downstream stage sees "the user as they were" a moment ago.
 */
public final class EnrichProcessor implements Processor<String, Transaction, String, EnrichedTransaction> {
    public static final String PROFILE_STORE = "profile-store";
    public static final String LAST_LOCATION_STORE = "last-location-store";

    private final Map<String, Integer> merchantRiskTiers;
    private ProcessorContext<String, EnrichedTransaction> context;
    private KeyValueStore<String, WelfordAccumulator> profiles;
    private KeyValueStore<String, LastLocation> locations;

    public EnrichProcessor(Map<String, Integer> merchantRiskTiers) {
        this.merchantRiskTiers = merchantRiskTiers == null ? Map.of() : Map.copyOf(merchantRiskTiers);
    }

    @Override
    public void init(ProcessorContext<String, EnrichedTransaction> context) {
        this.context = context;
        this.profiles = context.getStateStore(PROFILE_STORE);
        this.locations = context.getStateStore(LAST_LOCATION_STORE);
    }

    @Override
    public void process(Record<String, Transaction> record) {
        Transaction txn = record.value();
        int tier = merchantRiskTiers.getOrDefault(txn.merchantCategory(), 0);
        WelfordAccumulator profile = profiles.get(txn.userId());
        LastLocation last = locations.get(txn.userId());
        context.forward(record.withValue(new EnrichedTransaction(txn, tier, profile, last, System.nanoTime())));
    }
}
