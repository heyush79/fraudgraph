package com.fraudgraph.stream.scoring;

import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.model.FeatureVector;
import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.util.concurrent.TimeUnit;

/**
 * LLD §3.6 resilience. Wraps the gRPC client in a Resilience4j circuit breaker: count-based
 * sliding window, opens at the configured failure rate, half-open probe after the wait.
 * Open breaker (or any failure) → {@link ScoreResult#degraded()}, and the decision carries
 * {@code mode: DEGRADED}. The stream never stalls and never sees an exception from here.
 *
 * <p>Metrics: {@code fraudgraph_breaker_state} gauge (0 closed, 1 open, 2 half-open),
 * {@code fraudgraph_breaker_transitions_total{from,to}}, {@code fraudgraph_scorer_calls_total{outcome}},
 * {@code fraudgraph_scorer_latency}. Every state transition is also logged.
 */
public final class ResilientScoringClient implements ScoringClient, AutoCloseable {
    private static final Logger log = LoggerFactory.getLogger(ResilientScoringClient.class);

    private final ScoringClient delegate;
    private final CircuitBreaker breaker;
    private final MeterRegistry metrics;
    private final Timer latency;

    public ResilientScoringClient(ScoringClient delegate, FraudGraphProperties.Scoring.Breaker cfg, MeterRegistry metrics) {
        this.delegate = delegate;
        this.metrics = metrics;
        this.breaker = CircuitBreaker.of("scorer", CircuitBreakerConfig.custom()
                .slidingWindowType(CircuitBreakerConfig.SlidingWindowType.COUNT_BASED)
                .slidingWindowSize(cfg.window())
                .minimumNumberOfCalls(cfg.minCalls())
                .failureRateThreshold((float) (cfg.failureRate() * 100.0))
                .waitDurationInOpenState(Duration.ofSeconds(cfg.waitOpenSecs()))
                .permittedNumberOfCallsInHalfOpenState(cfg.halfOpenCalls())
                .automaticTransitionFromOpenToHalfOpenEnabled(true)
                .build());
        this.latency = Timer.builder("fraudgraph_scorer_latency")
                .description("round trip to the ML scorer, successful calls")
                .publishPercentiles(0.5, 0.95, 0.99)
                .register(metrics);
        metrics.gauge("fraudgraph_breaker_state", breaker, b -> stateCode(b.getState()));
        breaker.getEventPublisher().onStateTransition(e -> {
            var t = e.getStateTransition();
            log.warn("scorer breaker {} -> {}", t.getFromState(), t.getToState());
            metrics.counter("fraudgraph_breaker_transitions_total", "from", t.getFromState().name(), "to", t.getToState().name()).increment();
        });
    }

    @Override
    public ScoreResult score(FeatureVector fv) {
        long start = System.nanoTime();
        try {
            ScoreResult r = breaker.executeSupplier(() -> delegate.score(fv));
            latency.record(System.nanoTime() - start, TimeUnit.NANOSECONDS);
            metrics.counter("fraudgraph_scorer_calls_total", "outcome", "ok").increment();
            return r;
        } catch (CallNotPermittedException e) {
            metrics.counter("fraudgraph_scorer_calls_total", "outcome", "rejected").increment();
            return ScoreResult.degraded();
        } catch (RuntimeException e) {
            metrics.counter("fraudgraph_scorer_calls_total", "outcome", "error").increment();
            log.debug("scorer call failed for txn {}: {}", fv.txnId(), e.toString());
            return ScoreResult.degraded();
        }
    }

    public CircuitBreaker.State state() {
        return breaker.getState();
    }

    static int stateCode(CircuitBreaker.State s) {
        return switch (s) {
            case CLOSED -> 0;
            case OPEN, FORCED_OPEN -> 1;
            case HALF_OPEN -> 2;
            default -> 3;
        };
    }

    @Override
    public void close() throws Exception {
        if (delegate instanceof AutoCloseable c) c.close();
    }
}
