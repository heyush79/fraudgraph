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
 *
 * <p>Lossless as JSON, but not byte-for-byte. JSONB normalises whitespace, reorders object keys
 * and drops duplicate keys, so the text that comes back is semantically identical to what the
 * engine published and textually different. Everything downstream parses it, so this costs
 * nothing; assert on parsed structure rather than substrings.
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
