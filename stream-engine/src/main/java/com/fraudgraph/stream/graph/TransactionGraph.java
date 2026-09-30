package com.fraudgraph.stream.graph;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * In-memory P2P transfer graph (LLD §3.5). Adjacency capped at {@code maxEdgesPerNode}
 * most-recent edges per node, {@code edgeTtlMs} TTL evicted lazily on access, union-find
 * for components.
 *
 * <p>One instance per JVM, shared by all stream threads under a lock, rather than one per
 * thread as the LLD first sketched: partitions are keyed by userId, so a 4-account ring is
 * spread across up to 4 partitions and a per-thread graph would see only fragments of it.
 * The lock is cheap — the critical section is a deque append and a DFS that dies in a hop
 * or two for honest users. The limitation that remains is per <em>instance</em>: rings
 * split across engine instances are still missed (LLD §11.1). Not restored on restart
 * (in-memory by design); it warms back up within the 24h TTL.
 */
public final class TransactionGraph {
    /** Pass-through detection settings; see application.yml fraudgraph.graph for the reasoning. */
    public record PassThroughConfig(long windowMs, double minRatio, double maxRatio) {
        public static final PassThroughConfig DEFAULT = new PassThroughConfig(60 * 60_000L, 0.80, 1.02);
    }

    /** A transfer that arrived in a node: who sent it, how much, when, and its chain depth. */
    private record Inbound(String src, double amount, long tsMs, int depth) {}

    /** Long laundering chains exist, but beyond this the feature carries no extra information. */
    private static final int MAX_CHAIN_DEPTH = 10;

    private final int maxEdgesPerNode;
    private final long edgeTtlMs;
    private final int maxCycleDepth;
    private final PassThroughConfig passThrough;
    private final Map<String, Deque<Edge>> adjacency = new HashMap<>();
    private final Map<String, Deque<Inbound>> inbound = new HashMap<>();
    private final UnionFind components = new UnionFind();

    public TransactionGraph(int maxEdgesPerNode, long edgeTtlMs, int maxCycleDepth) {
        this(maxEdgesPerNode, edgeTtlMs, maxCycleDepth, PassThroughConfig.DEFAULT);
    }

    public TransactionGraph(int maxEdgesPerNode, long edgeTtlMs, int maxCycleDepth, PassThroughConfig passThrough) {
        this.maxEdgesPerNode = maxEdgesPerNode;
        this.edgeTtlMs = edgeTtlMs;
        this.maxCycleDepth = maxCycleDepth;
        this.passThrough = passThrough;
    }

    /**
     * Adds src → dst at {@code tsMs} and reports what the check stage needs. Self-edges are
     * ignored (a user "paying themself" is a wallet top-up, not a ring). Never throws.
     */
    public synchronized GraphView addEdge(String src, String dst, double amount, long tsMs) {
        if (src == null || dst == null || src.equals(dst)) {
            return view(src, tsMs, List.of());
        }
        // Read what arrived in src BEFORE recording this transfer, so a transfer never forwards itself.
        GraphView.PassThrough pt = passThroughFor(src, amount, tsMs);

        Deque<Edge> edges = adjacency.computeIfAbsent(src, k -> new ArrayDeque<>());
        expire(edges, tsMs);
        edges.addLast(new Edge(dst, amount, tsMs, pt.chainDepth()));
        while (edges.size() > maxEdgesPerNode) edges.pollFirst();

        Deque<Inbound> arrivals = inbound.computeIfAbsent(dst, k -> new ArrayDeque<>());
        arrivals.addLast(new Inbound(src, amount, tsMs, pt.chainDepth()));
        while (arrivals.size() > maxEdgesPerNode) arrivals.pollFirst();

        components.union(src, dst);

        List<String> cycle = CycleDetector.findCycle(src, dst, maxCycleDepth, node -> liveDestinations(node, tsMs));
        GraphView base = view(src, tsMs, cycle);
        return new GraphView(base.cycle(), base.outDegree(), base.componentSize(), pt);
    }

    /**
     * Does this outgoing transfer forward money that arrived in {@code src} shortly before?
     *
     * <p>Picks the most recent inbound within the window whose amount this transfer matches within
     * the ratio band; that is the money being forwarded, and the chain depth extends from it. When
     * nothing in the band matches, the most recent inbound is still reported (depth 0) so the model
     * can see "received ₹40,000, sent ₹300", which is evidence against pass-through.
     *
     * <p>Known limitation: the graph is shared across stream threads and each thread processes its
     * own partitions, so under a large replay backlog a forwarding hop can be processed before the
     * hop that funded it, and the match is missed. In steady state hops are minutes apart and
     * partitions are milliseconds apart.
     */
    private GraphView.PassThrough passThroughFor(String src, double amount, long tsMs) {
        Deque<Inbound> arrivals = inbound.get(src);
        if (arrivals == null) return GraphView.PassThrough.NONE;
        long cutoff = tsMs - passThrough.windowMs();
        arrivals.removeIf(i -> i.tsMs() < cutoff);
        if (arrivals.isEmpty()) {
            inbound.remove(src);
            return GraphView.PassThrough.NONE;
        }
        Inbound latest = null;
        Inbound match = null;
        for (Iterator<Inbound> it = arrivals.descendingIterator(); it.hasNext(); ) {
            Inbound i = it.next();
            if (i.tsMs() > tsMs) continue;          // stamped after this transfer: cannot be what it forwards
            if (latest == null) latest = i;
            double ratio = i.amount() > 0 ? amount / i.amount() : 0;
            if (ratio >= passThrough.minRatio() && ratio <= passThrough.maxRatio()) {
                match = i;
                break;
            }
        }
        Inbound used = match != null ? match : latest;
        if (used == null) return GraphView.PassThrough.NONE;
        double ratio = used.amount() > 0 ? Math.round(amount / used.amount() * 1000.0) / 1000.0 : 0.0;
        long secs = Math.max(0L, (tsMs - used.tsMs()) / 1000L);
        int depth = match != null ? Math.min(MAX_CHAIN_DEPTH, match.depth() + 1) : 0;
        return new GraphView.PassThrough(used.src(), used.amount(), ratio, secs, depth);
    }

    /** Read-only view for a user who did not transfer (card/UPI txn). */
    public synchronized GraphView view(String node, long tsMs) {
        return view(node, tsMs, List.of());
    }

    private GraphView view(String node, long tsMs, List<String> cycle) {
        if (node == null) return GraphView.NONE;
        Deque<Edge> edges = adjacency.get(node);
        int degree = 0;
        if (edges != null) {
            expire(edges, tsMs);
            degree = edges.size();
        }
        return new GraphView(cycle, degree, components.componentSizeIfKnown(node));
    }

    private List<String> liveDestinations(String node, long nowMs) {
        Deque<Edge> edges = adjacency.get(node);
        if (edges == null) return List.of();
        expire(edges, nowMs);
        List<String> out = new ArrayList<>(edges.size());
        for (Edge e : edges) out.add(e.dst());
        return out;
    }

    private void expire(Deque<Edge> edges, long nowMs) {
        long cutoff = nowMs - edgeTtlMs;
        Iterator<Edge> it = edges.iterator();
        while (it.hasNext()) {
            if (it.next().tsMs() < cutoff) it.remove(); else break; // deque is in insertion (time) order
        }
    }

    /** Neighbourhood for the read API (Phase 4/5): live out-edges of a node. */
    public synchronized List<Edge> outEdges(String node, long nowMs) {
        Deque<Edge> edges = adjacency.get(node);
        if (edges == null) return List.of();
        expire(edges, nowMs);
        return List.copyOf(edges);
    }

    public synchronized int nodeCount() {
        return adjacency.size();
    }

    /**
     * What the read API returns: the live sub-graph within {@code depth} hops of {@code root},
     * plus any cycles the root itself sits on. Field names follow LLD §6.1's
     * "nodes, edges, cycles, component size".
     */
    public record Neighborhood(List<Node> nodes, List<Edge> edges, List<List<String>> cycles, int componentSize) {
        public record Node(String id, int degree, int depth) {}
        /** {@code chainDepth} > 0 marks a pass-through hop, so a UI can draw the laundering chain. */
        public record Edge(String src, String dst, double amount, long tsMs, int chainDepth) {}
    }

    /**
     * Breadth-first walk of live out-edges from {@code root}, at most {@code depth} hops.
     * Bounded by the same 50-edges-per-node cap as detection, so the worst case is 50^depth
     * links; callers cap depth at 2 (LLD §6.1).
     */
    public synchronized Neighborhood neighborhood(String root, int depth, long nowMs) {
        if (root == null) return new Neighborhood(List.of(), List.of(), List.of(), 1);
        Map<String, Integer> seen = new LinkedHashMap<>();
        List<Neighborhood.Edge> edges = new ArrayList<>();
        Deque<String> frontier = new ArrayDeque<>();
        seen.put(root, 0);
        frontier.add(root);
        while (!frontier.isEmpty()) {
            String node = frontier.poll();
            int d = seen.get(node);
            if (d >= depth) continue;
            for (Edge e : liveEdges(node, nowMs)) {
                edges.add(new Neighborhood.Edge(node, e.dst(), e.amount(), e.tsMs(), e.depth()));
                if (!seen.containsKey(e.dst())) {
                    seen.put(e.dst(), d + 1);
                    frontier.add(e.dst());
                }
            }
        }
        List<Neighborhood.Node> nodes = new ArrayList<>(seen.size());
        for (var entry : seen.entrySet()) {
            nodes.add(new Neighborhood.Node(entry.getKey(), liveEdges(entry.getKey(), nowMs).size(), entry.getValue()));
        }
        return new Neighborhood(nodes, edges, cyclesThrough(root, nowMs), components.componentSizeIfKnown(root));
    }

    /**
     * Cycles the root sits on, one per out-edge that closes one, de-duplicated by node set.
     * This is the same bounded DFS the ring check runs, asked after the fact instead of on the
     * hot path, so the analyst agent's "is this user in a ring" answer and the engine's
     * RING_SUSPECT signal can never disagree.
     */
    private List<List<String>> cyclesThrough(String root, long nowMs) {
        List<List<String>> found = new ArrayList<>();
        Set<Set<String>> seenSets = new HashSet<>();
        for (Edge e : liveEdges(root, nowMs)) {
            List<String> cycle = CycleDetector.findCycle(root, e.dst(), maxCycleDepth, node -> liveDestinations(node, nowMs));
            if (!cycle.isEmpty() && seenSets.add(new HashSet<>(cycle))) {
                found.add(cycle);
            }
        }
        return found;
    }

    private List<Edge> liveEdges(String node, long nowMs) {
        Deque<Edge> edges = adjacency.get(node);
        if (edges == null) return List.of();
        expire(edges, nowMs);
        return List.copyOf(edges);
    }
}
