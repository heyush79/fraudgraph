package com.fraudgraph.stream.model;

import java.util.List;

/** Output of the check stage: the enriched txn, the fired signals and the assembled feature vector. */
public record CheckedTransaction(EnrichedTransaction enriched, List<RiskSignal> signals, FeatureVector features) {
    public CheckedTransaction {
        signals = signals == null ? List.of() : List.copyOf(signals);
    }
}
