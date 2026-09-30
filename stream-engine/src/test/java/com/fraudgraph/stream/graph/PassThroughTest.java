package com.fraudgraph.stream.graph;

import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;

/** Pass-through: money that arrives and leaves again at nearly the same amount. */
class PassThroughTest {
    private static final long TTL = Duration.ofHours(24).toMillis();
    private static final long MIN = 60_000L;
    private final TransactionGraph g = new TransactionGraph(50, TTL, 5);
    private final long t = 1_700_000_000_000L;

    @Test
    void theOriginOfAChainHasNoInbound() {
        GraphView v = g.addEdge("A", "B", 40_000, t);
        assertThat(v.passThrough()).isEqualTo(GraphView.PassThrough.NONE);
        assertThat(v.passThrough().forwards()).isFalse();
    }

    @Test
    void forwardingASimilarAmountExtendsTheChain() {
        g.addEdge("A", "B", 40_000, t);
        GraphView b = g.addEdge("B", "C", 38_800, t + 3 * MIN);   // 97%
        assertThat(b.passThrough().chainDepth()).isEqualTo(1);
        assertThat(b.passThrough().inboundFrom()).isEqualTo("A");
        assertThat(b.passThrough().ratio()).isEqualTo(0.97);
        assertThat(b.passThrough().secsSinceInbound()).isEqualTo(180);

        GraphView c = g.addEdge("C", "D", 37_000, t + 6 * MIN);
        assertThat(c.passThrough().chainDepth()).isEqualTo(2);
        assertThat(c.passThrough().inboundFrom()).isEqualTo("B");
    }

    @Test
    void theRatioBandIsInclusiveAndBoundsBothWays() {
        g.addEdge("A", "B", 1000, t);
        assertThat(g.addEdge("B", "C", 800, t + MIN).passThrough().chainDepth()).isEqualTo(1);   // exactly 0.80
        g.addEdge("P", "Q", 1000, t);
        assertThat(g.addEdge("Q", "R", 799, t + MIN).passThrough().chainDepth()).isZero();      // just below
        g.addEdge("X", "Y", 1000, t);
        assertThat(g.addEdge("Y", "Z", 1021, t + MIN).passThrough().chainDepth()).isZero();     // above 1.02: other money joined
    }

    @Test
    void anInboundOutsideTheWindowIsForgotten() {
        g.addEdge("A", "B", 40_000, t);
        GraphView v = g.addEdge("B", "C", 39_000, t + 61 * MIN);
        assertThat(v.passThrough()).isEqualTo(GraphView.PassThrough.NONE);
    }

    @Test
    void aMismatchedAmountStillReportsTheInboundAsContext() {
        g.addEdge("A", "B", 40_000, t);
        GraphView v = g.addEdge("B", "C", 300, t + 2 * MIN);
        assertThat(v.passThrough().chainDepth()).isZero();
        assertThat(v.passThrough().inboundFrom()).isEqualTo("A");   // the model sees that money did arrive
        assertThat(v.passThrough().ratio()).isEqualTo(0.008);
    }

    @Test
    void theMatchingInboundWinsOverAMoreRecentOneThatDoesNotMatch() {
        g.addEdge("A", "B", 40_000, t);            // the laundering inbound
        g.addEdge("F", "B", 250, t + MIN);         // a friend's unrelated transfer, more recent
        GraphView v = g.addEdge("B", "C", 38_000, t + 2 * MIN);
        assertThat(v.passThrough().chainDepth()).isEqualTo(1);
        assertThat(v.passThrough().inboundFrom()).isEqualTo("A");
    }

    @Test
    void aTransferNeverForwardsItself() {
        // the first outgoing transfer of a fresh account has nothing to forward, even though it
        // is itself an inbound for the receiver
        GraphView v = g.addEdge("A", "B", 5000, t);
        assertThat(v.passThrough().chainDepth()).isZero();
        assertThat(g.addEdge("A", "C", 5000, t + MIN).passThrough().chainDepth()).isZero();
    }

    @Test
    void anInboundStampedAfterTheOutboundIsIgnored() {
        g.addEdge("A", "B", 40_000, t + 10 * MIN);                 // arrives later in event time
        GraphView v = g.addEdge("B", "C", 39_000, t);             // processed after it, stamped before
        assertThat(v.passThrough().chainDepth()).isZero();
    }

    @Test
    void chainDepthIsCapped() {
        String prev = "n0";
        double amount = 100_000;
        g.addEdge("origin", prev, amount, t);
        GraphView last = null;
        for (int i = 1; i <= 15; i++) {
            amount *= 0.97;
            String next = "n" + i;
            last = g.addEdge(prev, next, amount, t + i * MIN);
            prev = next;
        }
        assertThat(last.passThrough().chainDepth()).isEqualTo(10);
    }

    @Test
    void neighborhoodEdgesCarryTheirChainDepth() {
        g.addEdge("A", "B", 40_000, t);
        g.addEdge("B", "C", 39_000, t + MIN);
        var n = g.neighborhood("B", 1, t + 2 * MIN);
        assertThat(n.edges()).singleElement().satisfies(e -> {
            assertThat(e.dst()).isEqualTo("C");
            assertThat(e.chainDepth()).isEqualTo(1);
        });
    }
}
