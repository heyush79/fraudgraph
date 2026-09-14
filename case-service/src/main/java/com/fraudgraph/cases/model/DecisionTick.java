package com.fraudgraph.cases.model;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * What goes down the WebSocket for every decision: enough for the live ticker to render a row
 * and link to a case, and nothing more. The full document is one REST call away.
 */
public record DecisionTick(
        String txnId,
        String userId,
        Verdict verdict,
        String mode,
        Double mlScore,
        List<String> firedRules,
        long latencyMs,
        Instant decidedAt,
        UUID caseId
) {
    public static DecisionTick of(DecisionDoc d, UUID caseId) {
        return new DecisionTick(d.txnId(), d.userId(), d.verdict(), d.mode(), d.mlScore(),
                d.firedRulesOrEmpty(), d.latencyMs(), d.decidedAt(), caseId);
    }
}
