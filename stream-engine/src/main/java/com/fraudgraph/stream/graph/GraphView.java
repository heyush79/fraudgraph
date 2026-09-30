package com.fraudgraph.stream.graph;

import java.util.List;

/**
 * What the check stage sees after the current transaction's edge (if any) is in the graph.
 * {@code cycle} is [src, …, src] when the new edge closed one, else empty.
 */
public record GraphView(List<String> cycle, int outDegree, int componentSize, PassThrough passThrough) {
    public static final GraphView NONE = new GraphView(List.of(), 0, 1, PassThrough.NONE);

    public GraphView {
        cycle = cycle == null ? List.of() : List.copyOf(cycle);
        passThrough = passThrough == null ? PassThrough.NONE : passThrough;
    }

    public GraphView(List<String> cycle, int outDegree, int componentSize) {
        this(cycle, outDegree, componentSize, PassThrough.NONE);
    }

    public boolean inCycle() {
        return !cycle.isEmpty();
    }

    /**
     * How this transfer relates to money the sender received shortly before. {@code inboundFrom}
     * is null when nothing arrived within the window; {@code chainDepth} is 0 unless the transfer
     * forwards a recent inbound at a similar amount.
     */
    public record PassThrough(String inboundFrom, double inboundAmount, double ratio,
                              long secsSinceInbound, int chainDepth) {
        public static final PassThrough NONE = new PassThrough(null, 0.0, 0.0, -1, 0);

        public boolean forwards() {
            return chainDepth > 0;
        }
    }
}
