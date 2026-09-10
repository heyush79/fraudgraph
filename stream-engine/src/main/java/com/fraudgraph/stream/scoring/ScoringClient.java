package com.fraudgraph.stream.scoring;

import com.fraudgraph.stream.model.FeatureVector;

/** Implementations: gRPC (breaker-wrapped, Phase 3) and Degraded. Must never throw or block past the timeout. */
public interface ScoringClient {
    ScoreResult score(FeatureVector fv);
}
