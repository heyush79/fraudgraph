package com.fraudgraph.stream.profile;

/**
 * Welford's online mean/variance (LLD §3.4): rolling amount statistics with no history kept.
 * Immutable record so it round-trips through the JSON profile-store unchanged.
 */
public record WelfordAccumulator(long n, double mean, double m2) {
    public static final WelfordAccumulator EMPTY = new WelfordAccumulator(0, 0.0, 0.0);

    public WelfordAccumulator add(double x) {
        long n1 = n + 1;
        double d = x - mean;
        double mean1 = mean + d / n1;
        double m21 = m2 + d * (x - mean1);
        return new WelfordAccumulator(n1, mean1, m21);
    }

    public double std() {
        return n > 1 ? Math.sqrt(m2 / (n - 1)) : 0.0;
    }

    /**
     * z-score of {@code x} against this history. 0 until {@code minSamples} are seen (a
     * profile of three purchases is noise) and 0 when std is below {@code minStd} (a user
     * who always pays exactly ₹100 would otherwise get an infinite z on ₹101).
     */
    public double zScore(double x, int minSamples, double minStd) {
        if (n < minSamples) return 0.0;
        double s = std();
        if (s < minStd) return 0.0;
        return (x - mean) / s;
    }
}
