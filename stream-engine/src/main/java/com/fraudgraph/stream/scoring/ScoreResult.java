package com.fraudgraph.stream.scoring;

import com.fraudgraph.stream.model.Decision;

import java.util.List;

/**
 * Outcome of asking the ML scorer.
 * <ul>
 *   <li>NOT_SCORED — nothing fired and the shadow sampler missed; model deliberately not called.</li>
 *   <li>SCORED — probability + top SHAP contributions (Phase 3).</li>
 *   <li>DEGRADED — model was needed but unavailable (breaker open / timeout / not deployed).</li>
 * </ul>
 */
public record ScoreResult(Status status, double probability, List<Decision.Contribution> contributions, String modelVersion) {
    public enum Status { NOT_SCORED, SCORED, DEGRADED }

    private static final ScoreResult NOT_SCORED = new ScoreResult(Status.NOT_SCORED, 0.0, List.of(), null);
    private static final ScoreResult DEGRADED = new ScoreResult(Status.DEGRADED, 0.0, List.of(), null);

    public static ScoreResult notScored() {
        return NOT_SCORED;
    }

    public static ScoreResult degraded() {
        return DEGRADED;
    }

    public static ScoreResult scored(double probability, List<Decision.Contribution> contributions, String modelVersion) {
        return new ScoreResult(Status.SCORED, probability, contributions == null ? List.of() : List.copyOf(contributions), modelVersion);
    }

    public boolean isScored() {
        return status == Status.SCORED;
    }

    public boolean isDegraded() {
        return status == Status.DEGRADED;
    }
}
