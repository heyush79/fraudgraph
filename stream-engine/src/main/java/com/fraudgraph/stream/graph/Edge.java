package com.fraudgraph.stream.graph;

/** A P2P transfer src → dst. src is the adjacency key, so only dst is stored. */
public record Edge(String dst, double amount, long tsMs) {}
