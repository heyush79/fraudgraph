package com.fraudgraph.cases.model;

import com.fasterxml.jackson.annotation.JsonRawValue;

import java.time.Instant;

/** One row of the append-only per-case audit trail (LLD §5.1). */
public record CaseEvent(String eventType, @JsonRawValue String payload, Instant at) {
    public static final String CREATED = "CREATED";
    public static final String STATUS_CHANGED = "STATUS_CHANGED";
    public static final String AGENT_STARTED = "AGENT_STARTED";
    public static final String REPORT_ATTACHED = "REPORT_ATTACHED";
}
