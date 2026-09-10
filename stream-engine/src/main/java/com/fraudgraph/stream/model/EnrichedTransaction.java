package com.fraudgraph.stream.model;

/**
 * Transaction plus what the enrich stage looked up. {@code ingestNanos} is the monotonic
 * time the record entered the topology so the decision can carry an honest latencyMs.
 */
public record EnrichedTransaction(Transaction txn, int merchantRiskTier, long ingestNanos) {}
