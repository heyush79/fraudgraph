package com.fraudgraph.stream.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;
import java.util.Map;

/**
 * Every tunable in the engine, bound from {@code fraudgraph.*} in application.yml.
 * The yml carries a one-line justification per number (LLD §9); keep it that way.
 */
@ConfigurationProperties(prefix = "fraudgraph")
public record FraudGraphProperties(
        Kafka kafka,
        Topics topics,
        Dedup dedup,
        Velocity velocity,
        Profile profile,
        Geo geo,
        Graph graph,
        Scoring scoring,
        Thresholds thresholds,
        Rules rules,
        Map<String, Integer> merchantRiskTiers
) {
    public record Kafka(String bootstrapServers, String applicationId, String stateDir,
                        int numStreamThreads, long commitIntervalMs, String processingGuarantee) {}

    public record Topics(String raw, String decisions, String dlq) {}

    public record Dedup(int ttlHours, int evictEveryMinutes) {}

    public record Velocity(int limit1m, int limit5m, int limit1h, int graceSecs) {}

    public record Profile(int minSamplesForZ, double minStd) {}

    public record Geo(double maxSpeedKmh, double minDistanceKm, long minGapSecs) {}

    public record Graph(int maxEdgesPerNode, int edgeTtlHours, int maxCycleDepth, int minCycleLength) {}

    public record Scoring(boolean enabled, String host, int port, long timeoutMs, double sampleRate, Breaker breaker) {
        public record Breaker(int window, int minCalls, double failureRate, int waitOpenSecs, int halfOpenCalls) {}
    }

    public record Thresholds(double block, double review, int minSignalsForReview, double minSignalSeverity) {}

    public record Rules(double amountCapInr, List<String> sanctionedMerchants) {}

    /** Defaults used by tests; mirrors application.yml. */
    public static FraudGraphProperties defaults() {
        return new FraudGraphProperties(
                new Kafka("localhost:29092", "fraudgraph-stream-engine-test", "/tmp/fraudgraph/state-test", 1, 100, "at_least_once"),
                new Topics("transactions.raw", "fraud.decisions", "transactions.dlq"),
                new Dedup(1, 1),
                new Velocity(8, 20, 60, 30),
                new Profile(10, 1.0),
                new Geo(900, 100, 60),
                new Graph(50, 24, 5, 3),
                new Scoring(false, "localhost", 50051, 150, 0.01, new Scoring.Breaker(50, 10, 0.5, 10, 5)),
                new Thresholds(0.85, 0.60, 2, 0.5),
                new Rules(200_000, List.of("m_CRYPTO_0013", "m_GAMBLING_0007")),
                Map.of("CRYPTO", 3, "GAMBLING", 3, "GIFT", 3, "ELEC", 2, "TRAVEL", 1, "P2P", 1)
        );
    }
}
