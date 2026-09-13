package com.fraudgraph.stream.check;

import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.graph.GraphView;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * LLD §3.5 ring detection. The CheckProcessor has already inserted this txn's P2P edge and
 * asked the graph for a view; if that view carries a cycle of at least {@code minCycleLength}
 * nodes, fire {@code RING_SUSPECT} with the cycle as evidence. A→B→A (length 2) is a
 * repayment between friends, not a ring, so it is excluded by default.
 */
public final class GraphCheck implements Check {
    private static final Logger log = LoggerFactory.getLogger(GraphCheck.class);
    public static final String CODE = "RING_SUSPECT";

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
            if (g == null || !g.inCycle()) return List.of();
            int length = g.cycle().size() - 1; // [A, B, C, A] is a 3-cycle
            if (length < cfg.minCycleLength()) return List.of();
            Map<String, Object> ev = new LinkedHashMap<>();
            ev.put("cycle", g.cycle());
            ev.put("cycleLength", length);
            ev.put("componentSize", g.componentSize());
            ev.put("outDegree", g.outDegree());
            ev.put("counterpartyId", txn.counterpartyId());
            return List.of(new RiskSignal(CODE, 1.0, ev));
        } catch (RuntimeException e) {
            log.warn("graph check failed for txn {}: {}", txn == null ? null : txn.txnId(), e.toString());
            return List.of();
        }
    }
}
