package com.fraudgraph.stream.graph;

import java.util.List;

/**
 * What the check stage sees after the current transaction's edge (if any) is in the graph.
 * {@code cycle} is [src, …, src] when the new edge closed one, else empty.
 */
public record GraphView(List<String> cycle, int outDegree, int componentSize) {
    public static final GraphView NONE = new GraphView(List.of(), 0, 1);

    public GraphView {
        cycle = cycle == null ? List.of() : List.copyOf(cycle);
    }

    public boolean inCycle() {
        return !cycle.isEmpty();
    }
}
