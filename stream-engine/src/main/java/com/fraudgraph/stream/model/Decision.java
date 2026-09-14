package com.fraudgraph.stream.model;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * One event on {@code fraud.decisions} (LLD §2.1) — the audit log.
 * {@code signals} is additive to the LLD schema: the analyst agent must cite evidence
 * (counts, distances, the ring's node list), and {@code firedRules} alone loses it.
 * {@code latencyMs} is end to end: transaction timestamp → decision.
 *
 * <p>{@code merchantId} and {@code merchantCategory} were added in Phase 5: the audit log was
 * dropping the merchant entirely, so a blocked transaction could not be explained without
 * going back to {@code transactions.raw}. The analyst agent has to cite its evidence, and
 * "blocked for a sanctioned merchant" with no merchant named is not a citable claim.
 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record Decision(
        String txnId,
        String userId,
        String merchantId,
        String merchantCategory,
        Verdict verdict,
        Mode mode,
        Double mlScore,
        List<String> firedRules,
        List<RiskSignal> signals,
        Map<String, Object> features,
        List<Contribution> contributions,
        long latencyMs,
        Instant decidedAt
) {
    public record Contribution(String feature, double shap) {}
}
