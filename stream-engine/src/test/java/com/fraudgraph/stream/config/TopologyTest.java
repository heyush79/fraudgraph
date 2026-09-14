package com.fraudgraph.stream.config;

import com.fraudgraph.stream.Fixtures;
import com.fraudgraph.stream.check.GeoCheck;
import com.fraudgraph.stream.check.GraphCheck;
import com.fraudgraph.stream.check.VelocityCheck;
import com.fraudgraph.stream.graph.TransactionGraph;
import com.fraudgraph.stream.model.Channel;
import com.fraudgraph.stream.model.Decision;
import com.fraudgraph.stream.model.Mode;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.model.Verdict;
import com.fraudgraph.stream.rules.AmountCapRule;
import com.fraudgraph.stream.rules.HardBlockMerchantRule;
import com.fraudgraph.stream.scoring.DegradedScoringClient;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.TestInputTopic;
import org.apache.kafka.streams.TestOutputTopic;
import org.apache.kafka.streams.TopologyTestDriver;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** End-to-end through the real topology, no broker: crafted txns in, decisions out. */
class TopologyTest {
    private final FraudGraphProperties props = FraudGraphProperties.defaults();
    private TopologyTestDriver driver;
    private TestInputTopic<String, Transaction> raw;
    private TestOutputTopic<String, Decision> decisions;
    private TestOutputTopic<String, Map> dlq;

    @BeforeEach
    void setUp() {
        start(new DegradedScoringClient());
    }

    private void start(com.fraudgraph.stream.scoring.ScoringClient scoringClient) {
        if (driver != null) driver.close();
        var g = props.graph();
        var graph = new TransactionGraph(g.maxEdgesPerNode(), Duration.ofHours(g.edgeTtlHours()).toMillis(), g.maxCycleDepth());
        var topology = new TopologyBuilder(props, scoringClient, graph, new SimpleMeterRegistry()).build();
        driver = new TopologyTestDriver(topology, KafkaStreamsConfig.testProperties(props));
        raw = driver.createInputTopic(props.topics().raw(), Serdes.String().serializer(), SerdeFactory.<Transaction>jsonSerializer());
        decisions = driver.createOutputTopic(props.topics().decisions(), Serdes.String().deserializer(), SerdeFactory.jsonDeserializer(Decision.class));
        dlq = driver.createOutputTopic(props.topics().dlq(), Serdes.String().deserializer(), SerdeFactory.jsonDeserializer(Map.class));
    }

    @AfterEach
    void tearDown() {
        driver.close();
    }

    private void pipe(Transaction t) {
        raw.pipeInput(t.userId(), t, t.ts());
    }

    @Test
    void cleanTransactionIsAllowedWithNoModelCall() {
        pipe(Fixtures.txn("u_1", 250.0, Fixtures.T0));
        Decision d = decisions.readValue();
        assertThat(d.verdict()).isEqualTo(Verdict.ALLOW);
        assertThat(d.mode()).isEqualTo(Mode.FULL);
        assertThat(d.mlScore()).isNull();
        assertThat(d.firedRules()).isEmpty();
        assertThat(d.features()).containsEntry("cnt1m", 1).containsEntry("cnt1h", 1).containsEntry("sum1h", 250.0).containsEntry("merchantRiskTier", 0).containsEntry("channel", "CARD");
        assertThat(d.latencyMs()).isGreaterThanOrEqualTo(0L); // end to end from the txn's own ts
        assertThat(d.signals()).isEmpty();
        assertThat(d.merchantId()).isEqualTo("m_GROC_0001");
        assertThat(d.merchantCategory()).isEqualTo("GROC");
        assertThat(d.features()).containsEntry("amtZ", 0.0).containsEntry("secsSinceLast", -1.0).containsEntry("componentSize", 1);
        assertThat(dlq.isEmpty()).isTrue();
    }

    @Test
    void duplicateTxnIdIsDroppedExactlyOnce() {
        Transaction t = Fixtures.txn("u_2", 10.0, Fixtures.T0);
        pipe(t);
        pipe(t);
        pipe(new Transaction(t.txnId(), t.userId(), t.merchantId(), null, 99.0, "INR", 0, 0, "d", t.channel(), t.ts().plusSeconds(5)));
        assertThat(decisions.readValuesToList()).hasSize(1);
    }

    @Test
    void velocityBurstBecomesReviewInDegradedMode() {
        int limit = props.velocity().limit1m();
        for (int i = 0; i <= limit; i++) {
            pipe(Fixtures.txn("u_3", 100.0, Fixtures.T0.plusSeconds(i * 3L)));
        }
        List<Decision> out = decisions.readValuesToList();
        assertThat(out).hasSize(limit + 1);
        for (int i = 0; i < limit; i++) {
            assertThat(out.get(i).verdict()).as("txn %d", i).isEqualTo(Verdict.ALLOW);
        }
        Decision last = out.get(limit);
        assertThat(last.verdict()).isEqualTo(Verdict.REVIEW);
        assertThat(last.mode()).isEqualTo(Mode.DEGRADED);
        assertThat(last.firedRules()).containsExactly(VelocityCheck.CODE_1M);
        assertThat(last.features()).containsEntry("cnt1m", limit + 1);
        assertThat(last.signals()).hasSize(1);
        assertThat(last.signals().get(0).evidence()).containsEntry("count", limit + 1);
    }

    @Test
    void scoredBurstIsBlockedInFullModeWithContributions() {
        start(fv -> com.fraudgraph.stream.scoring.ScoreResult.scored(0.93,
                List.of(new Decision.Contribution("cnt_1m", 0.42), new Decision.Contribution("merchant_risk_tier", 0.11)), "v1"));
        int limit = props.velocity().limit1m();
        for (int i = 0; i <= limit; i++) pipe(Fixtures.txn("u_ml", 100.0, Fixtures.T0.plusSeconds(i * 3L)));
        List<Decision> out = decisions.readValuesToList();
        Decision last = out.get(limit);
        assertThat(last.verdict()).isEqualTo(Verdict.BLOCK);
        assertThat(last.mode()).isEqualTo(Mode.FULL);
        assertThat(last.mlScore()).isEqualTo(0.93);
        assertThat(last.contributions()).extracting(Decision.Contribution::feature).containsExactly("cnt_1m", "merchant_risk_tier");
        assertThat(last.firedRules()).containsExactly(VelocityCheck.CODE_1M);
        // clean txns are not scored unless the shadow sampler hits
        assertThat(out.get(0).mlScore()).isNull();
    }

    @Test
    void impossibleTravelIsReviewedAndFeaturesCarryTheSpeed() {
        Transaction home = Fixtures.txn("u_geo", 100.0, Fixtures.T0);
        pipe(home);
        Transaction far = new Transaction("far-1", "u_geo", "m_GIFT_0001", null, 5000, "INR", 28.6139, 77.2090, "d_clone", Channel.CARD, Fixtures.T0.plusSeconds(300));
        pipe(far);
        List<Decision> out = decisions.readValuesToList();
        assertThat(out.get(0).verdict()).isEqualTo(Verdict.ALLOW);
        Decision d = out.get(1);
        assertThat(d.verdict()).isEqualTo(Verdict.REVIEW);
        assertThat(d.firedRules()).containsExactly(GeoCheck.CODE);
        assertThat((double) d.features().get("geoSpeedKmh")).isGreaterThan(900);
        assertThat(d.features()).containsEntry("secsSinceLast", 300.0).containsEntry("merchantRiskTier", 3);
        assertThat(d.signals().get(0).evidence()).containsKey("distanceKm");
    }

    @Test
    void ringClosesOnTheLastHopWithTheCycleAsEvidence() {
        String[] ring = {"u_a", "u_b", "u_c", "u_d"};
        for (int i = 0; i < ring.length; i++) {
            String src = ring[i], dst = ring[(i + 1) % ring.length];
            pipe(new Transaction("hop-" + i, src, "m_P2P_0000", dst, 40_000 - i * 1000, "INR", 17.38, 78.48, "d", Channel.P2P, Fixtures.T0.plusSeconds(i * 120L)));
        }
        List<Decision> out = decisions.readValuesToList();
        assertThat(out).hasSize(4);
        for (int i = 0; i < 3; i++) assertThat(out.get(i).verdict()).as("hop %d", i).isEqualTo(Verdict.ALLOW);
        Decision last = out.get(3);
        assertThat(last.verdict()).isEqualTo(Verdict.REVIEW);
        assertThat(last.firedRules()).containsExactly(GraphCheck.CODE);
        assertThat(last.features()).containsEntry("inCycle", true).containsEntry("componentSize", 4).containsEntry("nodeDegree", 1);
        assertThat(last.signals().get(0).evidence()).containsEntry("cycle", List.of("u_d", "u_a", "u_b", "u_c", "u_d"));
    }

    @Test
    void amountZScoreAppearsAfterTenTransactions() {
        for (int i = 0; i < 10; i++) {
            pipe(Fixtures.txn("u_z", i % 2 == 0 ? 90.0 : 110.0, Fixtures.T0.plus(Duration.ofMinutes(i * 10L))));
        }
        pipe(Fixtures.txn("u_z", 1000.0, Fixtures.T0.plus(Duration.ofMinutes(100))));
        List<Decision> out = decisions.readValuesToList();
        assertThat(out.get(9).features()).containsEntry("amtZ", 0.0);          // profile had 9 samples
        assertThat((double) out.get(10).features().get("amtZ")).isGreaterThan(50.0);
        assertThat(out.get(10).verdict()).isEqualTo(Verdict.ALLOW);            // z is a feature, not a rule
    }

    @Test
    void burstOutsideTheWindowDoesNotFire() {
        for (int i = 0; i < 20; i++) {
            pipe(Fixtures.txn("u_4", 100.0, Fixtures.T0.plus(Duration.ofSeconds(i * 61L))));
        }
        assertThat(decisions.readValuesToList()).allSatisfy(d -> assertThat(d.verdict()).isEqualTo(Verdict.ALLOW));
    }

    @Test
    void hardRulesBlockWithRuleCodeInFiredRules() {
        pipe(Fixtures.txn("u_5", "m_CRYPTO_0013", 10.0, Fixtures.T0));
        pipe(Fixtures.txn("u_6", 500_000.0, Fixtures.T0));
        List<Decision> out = decisions.readValuesToList();
        assertThat(out).extracting(Decision::verdict).containsExactly(Verdict.BLOCK, Verdict.BLOCK);
        assertThat(out.get(0).firedRules()).containsExactly(HardBlockMerchantRule.CODE);
        assertThat(out.get(0).features()).containsEntry("merchantRiskTier", 3);
        assertThat(out.get(1).firedRules()).containsExactly(AmountCapRule.CODE);
        // the merchant reaches the audit log, and the rule's evidence reaches the signals
        assertThat(out.get(0).merchantId()).isEqualTo("m_CRYPTO_0013");
        assertThat(out.get(0).merchantCategory()).isEqualTo("CRYPTO");
        assertThat(out.get(0).signals()).singleElement().satisfies(s -> {
            assertThat(s.code()).isEqualTo(HardBlockMerchantRule.CODE);
            assertThat(s.evidence()).containsEntry("merchantId", "m_CRYPTO_0013");
        });
        assertThat(out.get(1).signals()).singleElement().satisfies(s ->
                assertThat(s.evidence()).containsEntry("capInr", 200000.0));
    }

    @Test
    void dedupEntriesAreEvictedAfterTtlSoTheIdIsAcceptedAgain() {
        Transaction t = Fixtures.txn("u_7", 10.0, Fixtures.T0);
        pipe(t);
        // stream time must advance past ttl + punctuation interval; another user's txn does it
        Instant later = Fixtures.T0.plus(Duration.ofHours(1)).plus(Duration.ofMinutes(2));
        pipe(Fixtures.txn("u_8", 10.0, later));
        pipe(new Transaction(t.txnId(), t.userId(), t.merchantId(), null, 10.0, "INR", 0, 0, "d", t.channel(), later));
        assertThat(decisions.readValuesToList()).hasSize(3);
    }
}
