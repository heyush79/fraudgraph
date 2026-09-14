package com.fraudgraph.stream.graph;

import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;

class NeighborhoodTest {
    private static final long TTL = Duration.ofHours(24).toMillis();
    private final TransactionGraph g = new TransactionGraph(50, TTL, 5);
    private final long t = 1_700_000_000_000L;

    @Test
    void walksOutgoingEdgesToTheRequestedDepth() {
        g.addEdge("A", "B", 100, t);
        g.addEdge("B", "C", 90, t + 1);
        g.addEdge("C", "D", 80, t + 2);   // depth 3, must not appear at depth 2
        var n = g.neighborhood("A", 2, t + 10);
        assertThat(n.nodes()).extracting(TransactionGraph.Neighborhood.Node::id).containsExactlyInAnyOrder("A", "B", "C");
        assertThat(n.edges()).hasSize(2);
        assertThat(n.nodes()).filteredOn(x -> x.id().equals("C")).singleElement()
                .satisfies(c -> assertThat(c.depth()).isEqualTo(2));
        assertThat(n.componentSize()).isEqualTo(4);
    }

    @Test
    void handlesCyclesWithoutLooping() {
        g.addEdge("A", "B", 1, t);
        g.addEdge("B", "A", 1, t + 1);
        var n = g.neighborhood("A", 2, t + 2);
        assertThat(n.nodes()).hasSize(2);
        assertThat(n.edges()).hasSize(2);
        assertThat(n.cycles()).singleElement().isEqualTo(java.util.List.of("A", "B", "A"));
    }

    @Test
    void reportsTheRingTheUserSitsOn() {
        String[] ring = {"A", "B", "C", "D"};
        for (int i = 0; i < ring.length; i++) {
            g.addEdge(ring[i], ring[(i + 1) % ring.length], 40_000 - i * 100, t + i);
        }
        var n = g.neighborhood("A", 2, t + 10);
        assertThat(n.cycles()).singleElement().isEqualTo(java.util.List.of("A", "B", "C", "D", "A"));
        assertThat(n.componentSize()).isEqualTo(4);
        // depth 2 still only walks 2 hops of the edge list
        assertThat(n.nodes()).extracting(TransactionGraph.Neighborhood.Node::id).containsExactlyInAnyOrder("A", "B", "C");
    }

    @Test
    void aUserWithNoCycleReportsNone() {
        g.addEdge("A", "B", 1, t);
        g.addEdge("B", "C", 1, t + 1);
        assertThat(g.neighborhood("A", 2, t + 2).cycles()).isEmpty();
    }

    @Test
    void unknownUserIsJustItself() {
        // the root is always present so the dashboard draws one node rather than an empty box
        var n = g.neighborhood("ghost", 2, t);
        assertThat(n.nodes()).singleElement().satisfies(x -> {
            assertThat(x.id()).isEqualTo("ghost");
            assertThat(x.degree()).isZero();
            assertThat(x.depth()).isZero();
        });
        assertThat(n.edges()).isEmpty();
        assertThat(n.componentSize()).isEqualTo(1);
    }

    @Test
    void expiredEdgesAreNotReturned() {
        g.addEdge("A", "B", 1, t);
        var n = g.neighborhood("A", 2, t + TTL + 1000);
        assertThat(n.edges()).isEmpty();
    }
}
