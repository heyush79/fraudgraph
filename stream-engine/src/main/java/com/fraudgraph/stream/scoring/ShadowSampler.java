package com.fraudgraph.stream.scoring;

/**
 * Deterministic 1% (configurable) sample of clean traffic that still gets scored, so the
 * model's score distribution on ALLOW traffic is observable. Hash-based, not random, so a
 * replay of fraud.decisions is reproducible.
 */
public final class ShadowSampler {
    private final double rate;

    public ShadowSampler(double rate) {
        if (rate < 0.0 || rate > 1.0) throw new IllegalArgumentException("rate must be in [0,1]");
        this.rate = rate;
    }

    public boolean hit(String txnId) {
        if (rate <= 0.0 || txnId == null) return false;
        if (rate >= 1.0) return true;
        int h = txnId.hashCode();
        // spread the bits; String.hashCode on UUIDs is uneven in the low bits
        h ^= (h >>> 16);
        h *= 0x85ebca6b;
        h ^= (h >>> 13);
        double u = (h & 0x7fffffff) / (double) Integer.MAX_VALUE;
        return u < rate;
    }
}
