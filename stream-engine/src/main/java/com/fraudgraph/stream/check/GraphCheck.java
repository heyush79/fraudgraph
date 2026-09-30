package com.fraudgraph.stream.check;

import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.graph.GraphView;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * LLD §3.5 ring detection. The CheckProcessor has already inserted this txn's P2P edge and
 * asked the graph for a view; if that view carries a cycle of at least {@code minCycleLength}
 * nodes, fire {@code RING_SUSPECT} with the cycle as evidence. A→B→A (length 2) is a
 * repayment between friends, not a ring, so it is excluded by default.
 */
public final class GraphCheck implements Check {
    private static final Logger log = LoggerFactory.getLogger(GraphCheck.class);
    public static final String CODE = "RING_SUSPECT";
    public static final String PASS_THROUGH = "PASS_THROUGH";

    private final FraudGraphProperties.Graph cfg;

    public GraphCheck(FraudGraphProperties.Graph cfg) {
        this.cfg = cfg;
    }

    @Override
    public String name() {
        return "graph";
    }

    @Override
    public List<RiskSignal> evaluate(Transaction txn, CheckContext ctx) {
        try {
            GraphView g = ctx.graph();
            if (g == null) return List.of();
            List<RiskSignal> out = new ArrayList<>(2);
            ring(txn, g).ifPresent(out::add);
            passThrough(txn, g).ifPresent(out::add);
            return out;
        } catch (RuntimeException e) {
            log.warn("graph check failed for txn {}: {}", txn == null ? null : txn.txnId(), e.toString());
            return List.of();
        }
    }

    private Optional<RiskSignal> ring(Transaction txn, GraphView g) {
        if (!g.inCycle()) return Optional.empty();
        int length = g.cycle().size() - 1; // [A, B, C, A] is a 3-cycle
        if (length < cfg.minCycleLength()) return Optional.empty();
        Map<String, Object> ev = new LinkedHashMap<>();
        ev.put("cycle", g.cycle());
        ev.put("cycleLength", length);
        ev.put("componentSize", g.componentSize());
        ev.put("outDegree", g.outDegree());
        ev.put("counterpartyId", txn.counterpartyId());
        return Optional.of(new RiskSignal(CODE, 1.0, ev));
    }

    /**
     * Money that arrived shortly before and leaves again at nearly the same amount. This is the
     * signal that makes ring hops visible BEFORE the ring closes: in_cycle only exists on the
     * closing hop, and a transfer with no signal never reaches the model at all. Severity grows
     * with chain depth, because one forwarded transfer is ordinary (a friend passes on a share of
     * a bill) and three in a row is not.
     */
    private Optional<RiskSignal> passThrough(Transaction txn, GraphView g) {
        GraphView.PassThrough pt = g.passThrough();
        if (pt.chainDepth() < cfg.passThroughMinDepth()) return Optional.empty();
        double severity = Math.min(1.0, pt.chainDepth() / 3.0);
        Map<String, Object> ev = new LinkedHashMap<>();
        ev.put("inboundFrom", pt.inboundFrom());
        ev.put("inboundAmount", Math.round(pt.inboundAmount() * 100.0) / 100.0);
        ev.put("outboundAmount", Math.round(txn.amount() * 100.0) / 100.0);
        ev.put("ratio", pt.ratio());
        ev.put("secsSinceInbound", pt.secsSinceInbound());
        ev.put("chainDepth", pt.chainDepth());
        ev.put("counterpartyId", txn.counterpartyId());
        return Optional.of(new RiskSignal(PASS_THROUGH, severity, ev));
    }
}
