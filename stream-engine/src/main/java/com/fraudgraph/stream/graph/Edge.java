package com.fraudgraph.stream.graph;

/**
 * A P2P transfer src → dst. src is the adjacency key, so only dst is stored.
 *
 * <p>{@code depth} is the transfer's position in a pass-through chain: 0 for money that did not
 * arrive in src shortly before, n+1 when it forwards a transfer of depth n at a similar amount.
 */
public record Edge(String dst, double amount, long tsMs, int depth) {
    public Edge(String dst, double amount, long tsMs) {
        this(dst, amount, tsMs, 0);
    }
}
