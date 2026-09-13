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
    private final GraphCheck check = new GraphCheck(new FraudGraphProperties.Graph(50, 24, 5, 3));
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
    void noCycleNoSignalAndNullSafe() {
        assertThat(check.evaluate(p2p, ctx(GraphView.NONE))).isEmpty();
        assertThat(check.evaluate(p2p, ctx(null))).isEmpty();
    }
}
