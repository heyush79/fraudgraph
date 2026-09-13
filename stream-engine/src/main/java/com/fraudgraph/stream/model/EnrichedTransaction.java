package com.fraudgraph.stream.model;

import com.fraudgraph.stream.profile.LastLocation;
import com.fraudgraph.stream.profile.WelfordAccumulator;

/**
 * Transaction plus what the enrich stage looked up: static merchant tier, the user's
 * amount profile and last location <em>before</em> this txn (both null on first sight),
 * and the monotonic ingest time for the engine-internal latency timer.
 */
public record EnrichedTransaction(Transaction txn, int merchantRiskTier, WelfordAccumulator priorProfile,
                                  LastLocation lastLocation, long ingestNanos) {}
