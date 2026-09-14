package com.fraudgraph.cases.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonRawValue;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * A case as the API returns it. {@code decisionDoc} and {@code reportDoc} are passed through as
 * raw JSON straight from the JSONB columns: re-parsing them into Java types would be work that
 * only risks losing a field the engine or the agent added.
 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record FraudCase(
        UUID caseId,
        UUID txnId,
        String userId,
        Verdict verdict,
        Double mlScore,
        CaseStatus status,
        List<String> firedRules,
        Instant createdAt,
        Instant updatedAt,
        @JsonRawValue String decisionDoc,
        @JsonRawValue String reportDoc,
        List<CaseEvent> events
) {
}
