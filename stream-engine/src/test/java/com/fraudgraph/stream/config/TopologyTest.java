package com.fraudgraph.stream.config;

import com.fraudgraph.stream.Fixtures;
import com.fraudgraph.stream.check.VelocityCheck;
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
        var topology = new TopologyBuilder(props, new DegradedScoringClient(), new SimpleMeterRegistry()).build();
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
        assertThat(d.latencyMs()).isBetween(0L, 5_000L);
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
