package com.fraudgraph.stream.model;

import java.util.Map;

/**
 * Output of a {@link com.fraudgraph.stream.check.Check}. Severity is 0..1 and scales with
 * overshoot; evidence is whatever the analyst report needs to cite (counts, distances, cycles).
 */
public record RiskSignal(String code, double severity, Map<String, Object> evidence) {
    public RiskSignal {
        severity = Math.max(0.0, Math.min(1.0, severity));
        evidence = evidence == null ? Map.of() : Map.copyOf(evidence);
    }
}
