package com.fraudgraph.stream.config;

import org.apache.kafka.streams.KafkaStreams;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

/** /actuator/health reports DOWN unless the Streams instance is RUNNING (or still rebalancing). */
@Component
public class StreamsHealthIndicator implements HealthIndicator {
    private final KafkaStreamsConfig.StreamsLifecycle lifecycle;

    public StreamsHealthIndicator(KafkaStreamsConfig.StreamsLifecycle lifecycle) {
        this.lifecycle = lifecycle;
    }

    @Override
    public Health health() {
        KafkaStreams.State state = lifecycle.streams().state();
        Health.Builder b = switch (state) {
            case RUNNING, REBALANCING -> Health.up();
            case CREATED -> Health.unknown();
            default -> Health.down();
        };
        return b.withDetail("streamsState", state.name()).build();
    }
}
