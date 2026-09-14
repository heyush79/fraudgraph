package com.fraudgraph.cases.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * One event off {@code fraud.decisions}. Deliberately a separate declaration from the engine's
 * {@code Decision} record rather than a shared module: the two services are deployed and
 * versioned independently, and {@code @JsonIgnoreProperties} means the engine can add a field
 * without this consumer needing a release. The wire format is the contract, not a Java type.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record DecisionDoc(
        String txnId,
        String userId,
        String merchantId,
        String merchantCategory,
        Verdict verdict,
        String mode,
        Double mlScore,
        List<String> firedRules,
        List<Signal> signals,
        Map<String, Object> features,
        List<Contribution> contributions,
        long latencyMs,
        Instant decidedAt
) {
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Signal(String code, double severity, Map<String, Object> evidence) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Contribution(String feature, double shap) {}

    public List<String> firedRulesOrEmpty() {
        return firedRules == null ? List.of() : firedRules;
    }
}
