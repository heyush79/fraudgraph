package com.fraudgraph.stream.check;

import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.graph.GraphView;
import com.fraudgraph.stream.model.Channel;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class GraphCheckTest {
    private final GraphCheck check = new GraphCheck(new FraudGraphProperties.Graph(50, 24, 5, 3, 60, 0.80, 1.02, 1));
    private final Transaction p2p = new Transaction("t", "A", "m_P2P_0000", "B", 5000, "INR", 0, 0, "d", Channel.P2P, Instant.EPOCH);

    private static CheckContext ctx(GraphView g) {
        return new CheckContext(WindowAggregate.EMPTY, WindowAggregate.EMPTY, WindowAggregate.EMPTY, null, null, g);
    }

    @Test
    void ringFiresWithTheCycleAsEvidence() {
        List<RiskSignal> out = check.evaluate(p2p, ctx(new GraphView(List.of("A", "B", "C", "A"), 2, 3)));
        assertThat(out).hasSize(1);
        assertThat(out.get(0).code()).isEqualTo(GraphCheck.CODE);
        assertThat(out.get(0).severity()).isEqualTo(1.0);
        assertThat(out.get(0).evidence()).containsEntry("cycle", List.of("A", "B", "C", "A")).containsEntry("cycleLength", 3).containsEntry("componentSize", 3);
    }

    @Test
    void repaymentTwoCycleIsIgnored() {
        assertThat(check.evaluate(p2p, ctx(new GraphView(List.of("A", "B", "A"), 1, 2)))).isEmpty();
    }

    @Test
    void passThroughFiresWithItsEvidenceAndSeverityGrowsWithDepth() {
        var pt1 = new GraphView.PassThrough("u_z", 41230.5, 0.961, 184, 1);
        List<RiskSignal> out = check.evaluate(p2p, ctx(new GraphView(List.of(), 1, 2, pt1)));
        assertThat(out).singleElement().satisfies(s -> {
            assertThat(s.code()).isEqualTo(GraphCheck.PASS_THROUGH);
            assertThat(s.severity()).isCloseTo(1.0 / 3, org.assertj.core.data.Offset.offset(1e-9));
            assertThat(s.evidence()).containsEntry("inboundFrom", "u_z").containsEntry("inboundAmount", 41230.5)
                    .containsEntry("outboundAmount", 5000.0).containsEntry("ratio", 0.961)
                    .containsEntry("secsSinceInbound", 184L).containsEntry("chainDepth", 1)
                    .containsEntry("counterpartyId", "B");
        });
        var deep = new GraphView.PassThrough("u_z", 41230.5, 0.961, 184, 4);
        assertThat(check.evaluate(p2p, ctx(new GraphView(List.of(), 1, 2, deep))).get(0).severity()).isEqualTo(1.0);
    }

    @Test
    void aClosingHopCarriesBothSignals() {
        var pt = new GraphView.PassThrough("C", 39000, 0.97, 120, 3);
        List<RiskSignal> out = check.evaluate(p2p, ctx(new GraphView(List.of("A", "B", "C", "A"), 1, 3, pt)));
        assertThat(out).extracting(RiskSignal::code).containsExactly(GraphCheck.CODE, GraphCheck.PASS_THROUGH);
    }

    @Test
    void theMinimumDepthIsConfigurable() {
        var strict = new GraphCheck(new FraudGraphProperties.Graph(50, 24, 5, 3, 60, 0.80, 1.02, 2));
        var pt1 = new GraphView.PassThrough("u_z", 41230.5, 0.961, 184, 1);
        assertThat(strict.evaluate(p2p, ctx(new GraphView(List.of(), 1, 2, pt1)))).isEmpty();
    }

    @Test
    void noCycleNoSignalAndNullSafe() {
        assertThat(check.evaluate(p2p, ctx(GraphView.NONE))).isEmpty();
        assertThat(check.evaluate(p2p, ctx(null))).isEmpty();
    }
}
