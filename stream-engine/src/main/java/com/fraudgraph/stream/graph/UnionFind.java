package com.fraudgraph.stream.graph;

import java.util.HashMap;
import java.util.Map;

/**
 * Disjoint sets over string node ids with path compression and union by rank —
 * amortized near-O(1). Nodes are created on first sight. Components only ever merge;
 * edge expiry does not split them (LLD accepts this for v1: "who else is in this cluster?"
 * stays a superset, never a miss).
 */
public final class UnionFind {
    private final Map<String, String> parent = new HashMap<>();
    private final Map<String, Integer> rank = new HashMap<>();
    private final Map<String, Integer> size = new HashMap<>();

    public String find(String x) {
        String p = parent.get(x);
        if (p == null) {
            parent.put(x, x);
            rank.put(x, 0);
            size.put(x, 1);
            return x;
        }
        // iterative path compression
        String root = x;
        while (!parent.get(root).equals(root)) root = parent.get(root);
        String cur = x;
        while (!cur.equals(root)) {
            String next = parent.get(cur);
            parent.put(cur, root);
            cur = next;
        }
        return root;
    }

    public void union(String a, String b) {
        String ra = find(a), rb = find(b);
        if (ra.equals(rb)) return;
        int ka = rank.get(ra), kb = rank.get(rb);
        if (ka < kb) { String t = ra; ra = rb; rb = t; }
        parent.put(rb, ra);
        size.put(ra, size.get(ra) + size.get(rb));
        if (ka == kb) rank.put(ra, ka + 1);
    }

    public int componentSize(String x) {
        return size.get(find(x));
    }

    /** Size without inserting an unknown node: 1 for a node no edge has ever touched. */
    public int componentSizeIfKnown(String x) {
        return parent.containsKey(x) ? componentSize(x) : 1;
    }

    public int nodeCount() {
        return parent.size();
    }
}
