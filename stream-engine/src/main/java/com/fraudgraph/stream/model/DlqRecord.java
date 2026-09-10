package com.fraudgraph.stream.model;

import java.time.Instant;

/** Envelope on {@code transactions.dlq}: the offending payload plus why it failed. */
public record DlqRecord(String stage, String error, String payload, Instant failedAt) {}
