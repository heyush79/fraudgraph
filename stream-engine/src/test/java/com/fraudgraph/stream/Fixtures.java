package com.fraudgraph.stream;

import com.fraudgraph.stream.model.Channel;
import com.fraudgraph.stream.model.Transaction;

import java.time.Instant;
import java.util.UUID;

public final class Fixtures {
    public static final Instant T0 = Instant.parse("2026-09-04T10:15:03.120Z");

    private Fixtures() {}

    public static Transaction txn(String userId, double amount, Instant ts) {
        return txn(userId, "m_GROC_0001", amount, ts);
    }

    public static Transaction txn(String userId, String merchantId, double amount, Instant ts) {
        return new Transaction(UUID.randomUUID().toString(), userId, merchantId, null, amount, "INR",
                17.3850, 78.4867, "d_ab12", Channel.CARD, ts);
    }
}
