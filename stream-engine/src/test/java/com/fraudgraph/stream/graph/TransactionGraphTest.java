package com.fraudgraph.stream.graph;

import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class TransactionGraphTest {
    private static final long TTL = Duration.ofHours(24).toMillis();
    private final TransactionGraph g = new TransactionGraph(50, TTL, 5);
    private final long t = 1_700_000_000_000L;

    @Test
    void threeCycleIsFoundOnTheClosingEdge() {
        assertThat(g.addEdge("A", "B", 100, t).inCycle()).isFalse();
        assertThat(g.addEdge("B", "C", 95, t + 1000).inCycle()).isFalse();
        GraphView v = g.addEdge("C", "A", 90, t + 2000);
        assertThat(v.cycle()).containsExactly("C", "A", "B", "C");
        assertThat(v.componentSize()).isEqualTo(3);
        assertThat(v.outDegree()).isEqualTo(1);
    }

    @Test
    void twoCycleIsReportedByTheGraphAndFilteredByTheCheck() {
        g.addEdge("A", "B", 100, t);
        assertThat(g.addEdge("B", "A", 100, t + 1).cycle()).containsExactly("B", "A", "B");
    }

    @Test
    void depthBoundStopsLongCycles() {
        // 6-cycle A→B→C→D→E→F→A exceeds maxCycleDepth 5
        String[] n = {"A", "B", "C", "D", "E", "F"};
        for (int i = 0; i < 5; i++) g.addEdge(n[i], n[i + 1], 10, t + i);
        assertThat(g.addEdge("F", "A", 10, t + 6).inCycle()).isFalse();
        // but a 5-cycle is found
        TransactionGraph g5 = new TransactionGraph(50, TTL, 5);
        for (int i = 0; i < 4; i++) g5.addEdge(n[i], n[i + 1], 10, t + i);
        assertThat(g5.addEdge("E", "A", 10, t + 5).cycle()).hasSize(6);
    }

    @Test
    void selfEdgeIsIgnored() {
        GraphView v = g.addEdge("A", "A", 10, t);
        assertThat(v.inCycle()).isFalse();
        assertThat(v.outDegree()).isEqualTo(0);
        assertThat(g.nodeCount()).isEqualTo(0);
    }

    @Test
    void expiredEdgesDoNotCloseCycles() {
        g.addEdge("A", "B", 100, t);
        g.addEdge("B", "C", 100, t + 1000);
        assertThat(g.addEdge("C", "A", 100, t + TTL + 5000).inCycle()).isFalse();
        assertThat(g.outEdges("A", t + TTL + 5000)).isEmpty();
    }

    @Test
    void edgesPerNodeAreCapped() {
        TransactionGraph small = new TransactionGraph(3, TTL, 5);
        for (int i = 0; i < 10; i++) small.addEdge("A", "n" + i, 1, t + i);
        assertThat(small.outEdges("A", t + 10)).extracting(Edge::dst).containsExactly("n7", "n8", "n9");
        assertThat(small.view("A", t + 10).outDegree()).isEqualTo(3);
    }

    @Test
    void readOnlyViewForUnknownUserIsSingleton() {
        assertThat(g.view("nobody", t)).isEqualTo(GraphView.NONE);
        g.addEdge("A", "B", 1, t);
        assertThat(g.view("B", t).componentSize()).isEqualTo(2);
        assertThat(g.view("B", t).outDegree()).isEqualTo(0);
    }

    @Test
    void cycleDetectorHandlesBranchingWithoutRevisiting() {
        // A→B, A→C, B→D, C→D, D→A : cycle via either branch, visited set must not block the second
        g.addEdge("A", "B", 1, t);
        g.addEdge("A", "C", 1, t + 1);
        g.addEdge("B", "D", 1, t + 2);
        g.addEdge("C", "D", 1, t + 3);
        List<String> cycle = g.addEdge("D", "A", 1, t + 4).cycle();
        assertThat(cycle).startsWith("D", "A").endsWith("D").hasSize(4);
    }
}
