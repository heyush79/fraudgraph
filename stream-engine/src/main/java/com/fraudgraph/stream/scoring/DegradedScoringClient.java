package com.fraudgraph.stream.scoring;

import com.fraudgraph.stream.model.FeatureVector;

/**
 * Rules-only fallback. In Phase 1 it is the only client; from Phase 3 the circuit breaker
 * routes here while open. Every decision it touches is marked {@code mode: DEGRADED}.
 */
public final class DegradedScoringClient implements ScoringClient {
    @Override
    public ScoreResult score(FeatureVector fv) {
        return ScoreResult.degraded();
    }
}
