package com.fraudgraph.stream.config;

import com.fraudgraph.stream.graph.TransactionGraph;
import com.fraudgraph.stream.scoring.DegradedScoringClient;
import com.fraudgraph.stream.scoring.GrpcScoringClient;
import com.fraudgraph.stream.scoring.ResilientScoringClient;
import com.fraudgraph.stream.scoring.ScoringClient;
import io.micrometer.core.instrument.MeterRegistry;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.streams.KafkaStreams;
import org.apache.kafka.streams.StreamsConfig;
import org.apache.kafka.streams.Topology;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Properties;

@Configuration
public class KafkaStreamsConfig {
    private static final Logger log = LoggerFactory.getLogger(KafkaStreamsConfig.class);

    /**
     * Breaker-wrapped gRPC scorer (LLD §3.6). With scoring disabled the engine runs rules-only
     * and every scored decision is DEGRADED — same behaviour as an open breaker, by design.
     */
    @Bean(destroyMethod = "close")
    public ScoringClient scoringClient(FraudGraphProperties props, MeterRegistry metrics) {
        var s = props.scoring();
        if (!s.enabled()) {
            log.warn("scoring disabled: rules-only, every flagged decision will be DEGRADED");
            return new DegradedScoringClient();
        }
        log.info("scoring via gRPC {}:{} timeout {}ms, breaker window {} / {}% / {}s",
                s.host(), s.port(), s.timeoutMs(), s.breaker().window(), (int) (s.breaker().failureRate() * 100), s.breaker().waitOpenSecs());
        return new ResilientScoringClient(new GrpcScoringClient(s.host(), s.port(), s.timeoutMs()), s.breaker(), metrics);
    }

    /** One graph per engine instance, shared by every stream thread (see TransactionGraph javadoc). */
    @Bean
    public TransactionGraph transactionGraph(FraudGraphProperties props, MeterRegistry metrics) {
        var g = props.graph();
        TransactionGraph graph = new TransactionGraph(g.maxEdgesPerNode(), java.time.Duration.ofHours(g.edgeTtlHours()).toMillis(), g.maxCycleDepth());
        metrics.gauge("fraudgraph_graph_nodes", graph, TransactionGraph::nodeCount);
        return graph;
    }

    @Bean
    public Topology topology(FraudGraphProperties props, ScoringClient scoringClient, TransactionGraph graph, MeterRegistry metrics) {
        Topology t = new TopologyBuilder(props, scoringClient, graph, metrics).build();
        log.info("topology:\n{}", t.describe());
        return t;
    }

    @Bean
    public Properties streamsProperties(FraudGraphProperties props) {
        var k = props.kafka();
        Properties p = new Properties();
        p.put(StreamsConfig.APPLICATION_ID_CONFIG, k.applicationId());
        p.put(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, k.bootstrapServers());
        p.put(StreamsConfig.STATE_DIR_CONFIG, k.stateDir());
        p.put(StreamsConfig.NUM_STREAM_THREADS_CONFIG, k.numStreamThreads());
        p.put(StreamsConfig.COMMIT_INTERVAL_MS_CONFIG, k.commitIntervalMs());
        p.put(StreamsConfig.PROCESSING_GUARANTEE_CONFIG, k.processingGuarantee());
        p.put(StreamsConfig.DEFAULT_DESERIALIZATION_EXCEPTION_HANDLER_CLASS_CONFIG, DlqDeserializationExceptionHandler.class);
        p.put(DlqDeserializationExceptionHandler.DLQ_TOPIC_CONFIG, props.topics().dlq());
        // single-node demo: changelog/repartition topics can't have RF > 1
        p.put(StreamsConfig.REPLICATION_FACTOR_CONFIG, 1);
        p.put(StreamsConfig.consumerPrefix(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG), "latest");
        return p;
    }

    @Bean
    public StreamsLifecycle streamsLifecycle(Topology topology, Properties streamsProperties) {
        return new StreamsLifecycle(topology, streamsProperties);
    }

    public static Properties testProperties(FraudGraphProperties props) {
        Properties p = new KafkaStreamsConfig().streamsProperties(props);
        p.remove(StreamsConfig.DEFAULT_DESERIALIZATION_EXCEPTION_HANDLER_CLASS_CONFIG);
        return p;
    }

    /** Starts/stops the KafkaStreams instance with the Spring context; exposes state for health. */
    public static final class StreamsLifecycle implements org.springframework.context.SmartLifecycle {
        private final KafkaStreams streams;
        private volatile boolean running;

        StreamsLifecycle(Topology topology, Properties props) {
            this.streams = new KafkaStreams(topology, props);
            this.streams.setStateListener((next, prev) -> log.info("streams state {} -> {}", prev, next));
            this.streams.setUncaughtExceptionHandler(e -> {
                log.error("uncaught exception in stream thread, replacing thread", e);
                return org.apache.kafka.streams.errors.StreamsUncaughtExceptionHandler.StreamThreadExceptionResponse.REPLACE_THREAD;
            });
        }

        public KafkaStreams streams() {
            return streams;
        }

        @Override
        public void start() {
            streams.start();
            running = true;
        }

        @Override
        public void stop() {
            streams.close(java.time.Duration.ofSeconds(30));
            running = false;
        }

        @Override
        public boolean isRunning() {
            return running;
        }
    }
}
