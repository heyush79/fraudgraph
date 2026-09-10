package com.fraudgraph.stream.model;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.time.Instant;

/** One event on {@code transactions.raw} (LLD §2.1). Field names are the wire names. */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record Transaction(
        String txnId,
        String userId,
        String merchantId,
        String counterpartyId,
        double amount,
        String currency,
        double lat,
        double lon,
        String deviceId,
        Channel channel,
        Instant ts
) {
    /** Merchant category = middle token of {@code m_<CAT>_<nnnn>}; "UNKNOWN" if malformed. */
    public String merchantCategory() {
        if (merchantId == null) return "UNKNOWN";
        String[] parts = merchantId.split("_");
        return parts.length >= 3 ? parts[1] : "UNKNOWN";
    }
}
