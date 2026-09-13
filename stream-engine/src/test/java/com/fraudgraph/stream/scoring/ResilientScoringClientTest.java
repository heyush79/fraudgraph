package com.fraudgraph.stream.scoring;

import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.model.Channel;
import com.fraudgraph.stream.model.FeatureVector;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

class ResilientScoringClientTest {
    private static final FeatureVector FV = new FeatureVector("t", 1, 1, 1, 1, 0, 0, 1, 0, 0, false, 1, Channel.UPI);

    @Test
    void opensAfterFailuresFailsFastAndRecoversViaHalfOpen() throws Exception {
        AtomicBoolean healthy = new AtomicBoolean(false);
        AtomicInteger calls = new AtomicInteger();
        ScoringClient flaky = fv -> {
            calls.incrementAndGet();
            if (!healthy.get()) throw new IllegalStateException("UNAVAILABLE");
            return ScoreResult.scored(0.2, List.of(), "v1");
        };
        var registry = new SimpleMeterRegistry();
        var cfg = new FraudGraphProperties.Scoring.Breaker(50, 10, 0.5, 1, 3);
        var client = new ResilientScoringClient(flaky, cfg, registry);

        // 10 failures: each returns degraded, never throws
        for (int i = 0; i < 10; i++) assertThat(client.score(FV).isDegraded()).isTrue();
        assertThat(client.state()).isEqualTo(CircuitBreaker.State.OPEN);
        assertThat(registry.find("fraudgraph_breaker_state").gauge().value()).isEqualTo(1.0);

        // open: rejected without touching the delegate
        int before = calls.get();
        for (int i = 0; i < 20; i++) assertThat(client.score(FV).isDegraded()).isTrue();
        assertThat(calls.get()).isEqualTo(before);
        assertThat(registry.find("fraudgraph_scorer_calls_total").tag("outcome", "rejected").counter().count()).isEqualTo(20.0);

        // scorer comes back; after the wait the breaker half-opens, probes succeed, closes
        healthy.set(true);
        Thread.sleep(1200);
        for (int i = 0; i < 3; i++) assertThat(client.score(FV).isScored()).isTrue();
        assertThat(client.state()).isEqualTo(CircuitBreaker.State.CLOSED);
        assertThat(registry.find("fraudgraph_breaker_transitions_total").tag("to", "OPEN").counter().count()).isEqualTo(1.0);
        assertThat(registry.find("fraudgraph_breaker_transitions_total").tag("to", "CLOSED").counter().count()).isEqualTo(1.0);
        assertThat(registry.find("fraudgraph_scorer_latency").timer().count()).isEqualTo(3);
    }

    @Test
    void healthyDelegateIsPassedThrough() {
        var client = new ResilientScoringClient(fv -> ScoreResult.scored(0.7, List.of(), "v2"),
                new FraudGraphProperties.Scoring.Breaker(50, 10, 0.5, 10, 5), new SimpleMeterRegistry());
        assertThat(client.score(FV).probability()).isEqualTo(0.7);
        assertThat(client.state()).isEqualTo(CircuitBreaker.State.CLOSED);
    }
}
