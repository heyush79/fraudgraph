package com.fraudgraph.stream.model;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/** One event on {@code fraud.decisions} (LLD §2.1) — the audit log. */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record Decision(
        String txnId,
        String userId,
        Verdict verdict,
        Mode mode,
        Double mlScore,
        List<String> firedRules,
        Map<String, Object> features,
        List<Contribution> contributions,
        long latencyMs,
        Instant decidedAt
) {
    public record Contribution(String feature, double shap) {}
}
