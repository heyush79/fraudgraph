package com.fraudgraph.stream.config;

import com.fraudgraph.stream.check.Check;
import com.fraudgraph.stream.check.GeoCheck;
import com.fraudgraph.stream.check.GraphCheck;
import com.fraudgraph.stream.check.VelocityCheck;
import com.fraudgraph.stream.check.VelocityWindows;
import com.fraudgraph.stream.check.WindowAggregate;
import com.fraudgraph.stream.decision.DecisionAssembler;
import com.fraudgraph.stream.decision.ThresholdPolicy;
import com.fraudgraph.stream.graph.TransactionGraph;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.profile.LastLocation;
import com.fraudgraph.stream.profile.WelfordAccumulator;
import com.fraudgraph.stream.processor.CheckProcessor;
import com.fraudgraph.stream.processor.DecisionProcessor;
import com.fraudgraph.stream.processor.DedupProcessor;
import com.fraudgraph.stream.processor.EnrichProcessor;
import com.fraudgraph.stream.rules.AmountCapRule;
import com.fraudgraph.stream.rules.HardBlockMerchantRule;
import com.fraudgraph.stream.rules.RuleEngine;
import com.fraudgraph.stream.scoring.ScoringClient;
import com.fraudgraph.stream.scoring.ShadowSampler;
import io.micrometer.core.instrument.MeterRegistry;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.Topology;
import org.apache.kafka.streams.state.Stores;

import java.time.Duration;
import java.util.List;

/**
 * LLD §3.1, Processor API end to end:
 * <pre>
 * transactions.raw → dedup → enrich → check → decision → fraud.decisions | transactions.dlq
 * </pre>
 * Kept free of Spring so {@code TopologyTestDriver} tests can build it directly.
 */
public final class TopologyBuilder {
    public static final String SOURCE = "raw-source";
    public static final String DEDUP = "dedup";
    public static final String ENRICH = "enrich";
    public static final String CHECK = "check";
    public static final String DECISION = "decision";

    private final FraudGraphProperties props;
    private final ScoringClient scoringClient;
    private final TransactionGraph graph;
    private final MeterRegistry metrics;

    public TopologyBuilder(FraudGraphProperties props, ScoringClient scoringClient, TransactionGraph graph, MeterRegistry metrics) {
        this.props = props;
        this.scoringClient = scoringClient;
        this.graph = graph;
        this.metrics = metrics;
    }

    public Topology build() {
        var txnSerde = SerdeFactory.json(Transaction.class);
        var aggSerde = SerdeFactory.json(WindowAggregate.class);
        Duration grace = Duration.ofSeconds(props.velocity().graceSecs());

        List<Check> checks = List.of(
                new VelocityCheck(props.velocity()),
                new GeoCheck(props.geo()),
                new GraphCheck(props.graph()));
        RuleEngine rules = new RuleEngine(List.of(
                new HardBlockMerchantRule(props.rules().sanctionedMerchants()),
                new AmountCapRule(props.rules().amountCapInr())));
        ThresholdPolicy policy = new ThresholdPolicy(props.thresholds(), rules);

        Topology t = new Topology();
        t.addSource(Topology.AutoOffsetReset.LATEST, SOURCE, new TransactionTimestampExtractor(),
                Serdes.String().deserializer(), txnSerde.deserializer(), props.topics().raw());

        t.addProcessor(DEDUP, () -> new DedupProcessor(
                Duration.ofHours(props.dedup().ttlHours()),
                Duration.ofMinutes(props.dedup().evictEveryMinutes()),
                metrics), SOURCE);
        t.addStateStore(Stores.keyValueStoreBuilder(
                Stores.persistentKeyValueStore(DedupProcessor.STORE), Serdes.String(), Serdes.Long()), DEDUP);

        t.addProcessor(ENRICH, () -> new EnrichProcessor(props.merchantRiskTiers()), DEDUP);
        t.addProcessor(CHECK, () -> new CheckProcessor(checks, graph, props.profile(), props.geo(), metrics), ENRICH);

        // profile + last-location: read by ENRICH, written by CHECK (LLD §3.1)
        t.addStateStore(Stores.keyValueStoreBuilder(
                Stores.persistentKeyValueStore(EnrichProcessor.PROFILE_STORE),
                Serdes.String(), SerdeFactory.json(WelfordAccumulator.class)), ENRICH, CHECK);
        t.addStateStore(Stores.keyValueStoreBuilder(
                Stores.persistentKeyValueStore(EnrichProcessor.LAST_LOCATION_STORE),
                Serdes.String(), SerdeFactory.json(LastLocation.class)), ENRICH, CHECK);

        for (var w : List.of(
                new Object[]{VelocityWindows.STORE_1M, VelocityWindows.WINDOW_1M},
                new Object[]{VelocityWindows.STORE_5M, VelocityWindows.WINDOW_5M},
                new Object[]{VelocityWindows.STORE_1H, VelocityWindows.WINDOW_1H})) {
            String name = (String) w[0];
            Duration window = (Duration) w[1];
            t.addStateStore(Stores.windowStoreBuilder(
                    Stores.persistentWindowStore(name, window.plus(grace), VelocityWindows.bucketSize(window), false),
                    Serdes.String(), aggSerde), CHECK);
        }

        t.addProcessor(DECISION, () -> new DecisionProcessor(
                scoringClient,
                new ShadowSampler(props.scoring().sampleRate()),
                policy,
                new DecisionAssembler(),
                metrics), CHECK);

        t.addSink(DecisionProcessor.DECISIONS_SINK, props.topics().decisions(),
                Serdes.String().serializer(), SerdeFactory.jsonSerializer(), DECISION);
        t.addSink(DecisionProcessor.DLQ_SINK, props.topics().dlq(),
                Serdes.String().serializer(), SerdeFactory.jsonSerializer(), DECISION);
        return t;
    }
}
