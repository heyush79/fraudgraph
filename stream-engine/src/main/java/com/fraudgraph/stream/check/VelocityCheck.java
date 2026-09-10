package com.fraudgraph.stream.check;

import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * LLD §3.5: fires {@code VELOCITY_1M/5M/1H} when the window count exceeds its limit.
 * Severity = min(1, (count − limit) / limit). Evidence = the counts, verbatim, for the report.
 */
public final class VelocityCheck implements Check {
    private static final Logger log = LoggerFactory.getLogger(VelocityCheck.class);

    public static final String CODE_1M = "VELOCITY_1M";
    public static final String CODE_5M = "VELOCITY_5M";
    public static final String CODE_1H = "VELOCITY_1H";

    private final FraudGraphProperties.Velocity limits;

    public VelocityCheck(FraudGraphProperties.Velocity limits) {
        this.limits = limits;
    }

    @Override
    public String name() {
        return "velocity";
    }

    @Override
    public List<RiskSignal> evaluate(Transaction txn, CheckContext ctx) {
        try {
            List<RiskSignal> out = new ArrayList<>(3);
            signal(CODE_1M, ctx.last1m(), limits.limit1m(), 60).ifPresent(out::add);
            signal(CODE_5M, ctx.last5m(), limits.limit5m(), 300).ifPresent(out::add);
            signal(CODE_1H, ctx.last1h(), limits.limit1h(), 3600).ifPresent(out::add);
            return out;
        } catch (RuntimeException e) {
            log.warn("velocity check failed for txn {}: {}", txn == null ? null : txn.txnId(), e.toString());
            return List.of();
        }
    }

    static java.util.Optional<RiskSignal> signal(String code, WindowAggregate agg, int limit, int windowSecs) {
        if (agg == null || limit <= 0 || agg.count() <= limit) {
            return java.util.Optional.empty();
        }
        double severity = Math.min(1.0, (double) (agg.count() - limit) / limit);
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("count", agg.count());
        evidence.put("limit", limit);
        evidence.put("windowSecs", windowSecs);
        evidence.put("sum", Math.round(agg.sum() * 100.0) / 100.0);
        return java.util.Optional.of(new RiskSignal(code, severity, evidence));
    }
}
