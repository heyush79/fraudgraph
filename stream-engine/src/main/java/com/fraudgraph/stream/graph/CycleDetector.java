package com.fraudgraph.stream.graph;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

/**
 * Bounded DFS (LLD §3.5). After edge src → dst is added, walk outgoing edges from dst looking
 * for src within {@code maxDepth} hops. A hit means the money went around: src → dst → … → src.
 * Visited-set pruning keeps the worst case at O(b^maxDepth) with b ≤ maxEdgesPerNode; in
 * practice honest users never form cycles and the search dies after a hop or two.
 */
public final class CycleDetector {
    private CycleDetector() {}

    /**
     * @param outgoing adjacency lookup; must return live (non-expired) destinations
     * @return the cycle as [src, dst, …, src] or an empty list
     */
    public static List<String> findCycle(String src, String dst, int maxDepth, Function<String, List<String>> outgoing) {
        if (src == null || dst == null || maxDepth < 2) return List.of();
        if (src.equals(dst)) return List.of();
        Deque<String> path = new ArrayDeque<>();
        path.addLast(src);
        path.addLast(dst);
        Set<String> onPath = new HashSet<>(path);
        return dfs(src, dst, 1, maxDepth, outgoing, path, onPath) ? new ArrayList<>(path) : List.of();
    }

    private static boolean dfs(String target, String node, int depth, int maxDepth,
                               Function<String, List<String>> outgoing, Deque<String> path, Set<String> onPath) {
        for (String next : outgoing.apply(node)) {
            if (next.equals(target)) {
                path.addLast(target);
                return true;
            }
            if (depth + 1 > maxDepth - 1 || onPath.contains(next)) continue; // need one more hop to close
            path.addLast(next);
            onPath.add(next);
            if (dfs(target, next, depth + 1, maxDepth, outgoing, path, onPath)) return true;
            path.removeLast();
            onPath.remove(next);
        }
        return false;
    }

    /** Convenience for callers holding a raw adjacency map of Edge deques. */
    public static Function<String, List<String>> adjacency(Map<String, ? extends Iterable<Edge>> adj) {
        return node -> {
            Iterable<Edge> edges = adj.get(node);
            if (edges == null) return List.of();
            List<String> out = new ArrayList<>();
            for (Edge e : edges) out.add(e.dst());
            return out;
        };
    }
}
