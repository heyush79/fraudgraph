package com.fraudgraph.stream.processor;

import com.fraudgraph.stream.check.Check;
import com.fraudgraph.stream.check.CheckContext;
import com.fraudgraph.stream.check.VelocityWindows;
import com.fraudgraph.stream.check.WindowAggregate;
import com.fraudgraph.stream.model.CheckedTransaction;
import com.fraudgraph.stream.model.EnrichedTransaction;
import com.fraudgraph.stream.model.FeatureVector;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import io.micrometer.core.instrument.MeterRegistry;
import org.apache.kafka.streams.processor.api.Processor;
import org.apache.kafka.streams.processor.api.ProcessorContext;
import org.apache.kafka.streams.processor.api.Record;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;

/**
 * Updates the velocity windows with the current txn, snapshots the state the checks need
 * into a {@link CheckContext}, runs every check, and assembles the feature vector.
 * Checks are isolated: one throwing never stops the others or the stream.
 */
public final class CheckProcessor implements Processor<String, EnrichedTransaction, String, CheckedTransaction> {
    private static final Logger log = LoggerFactory.getLogger(CheckProcessor.class);

    private final List<Check> checks;
    private final MeterRegistry metrics;

    private ProcessorContext<String, CheckedTransaction> context;
    private VelocityWindows w1m;
    private VelocityWindows w5m;
    private VelocityWindows w1h;

    public CheckProcessor(List<Check> checks, MeterRegistry metrics) {
        this.checks = List.copyOf(checks);
        this.metrics = metrics;
    }

    @Override
    public void init(ProcessorContext<String, CheckedTransaction> context) {
        this.context = context;
        this.w1m = new VelocityWindows(context.getStateStore(VelocityWindows.STORE_1M), VelocityWindows.WINDOW_1M);
        this.w5m = new VelocityWindows(context.getStateStore(VelocityWindows.STORE_5M), VelocityWindows.WINDOW_5M);
        this.w1h = new VelocityWindows(context.getStateStore(VelocityWindows.STORE_1H), VelocityWindows.WINDOW_1H);
    }

    @Override
    public void process(Record<String, EnrichedTransaction> record) {
        EnrichedTransaction enriched = record.value();
        Transaction txn = enriched.txn();
        long ts = record.timestamp();

        // write first, then read: the current txn is part of its own window
        w1m.record(txn.userId(), txn.amount(), ts);
        w5m.record(txn.userId(), txn.amount(), ts);
        w1h.record(txn.userId(), txn.amount(), ts);

        WindowAggregate a1m = w1m.aggregate(txn.userId(), ts);
        WindowAggregate a5m = w5m.aggregate(txn.userId(), ts);
        WindowAggregate a1h = w1h.aggregate(txn.userId(), ts);
        CheckContext ctx = new CheckContext(a1m, a5m, a1h);

        List<RiskSignal> signals = new ArrayList<>();
        for (Check check : checks) {
            try {
                List<RiskSignal> out = check.evaluate(txn, ctx);
                signals.addAll(out);
                for (RiskSignal s : out) {
                    metrics.counter("fraudgraph_signals_total", "code", s.code()).increment();
                }
            } catch (RuntimeException e) { // checks promise not to throw; belt and braces
                metrics.counter("fraudgraph_check_errors_total", "check", check.name()).increment();
                log.error("check {} threw for txn {}", check.name(), txn.txnId(), e);
            }
        }

        FeatureVector fv = new FeatureVector(
                txn.txnId(),
                (int) a1m.count(), (int) a5m.count(), (int) a1h.count(), a1h.sum(),
                0.0,   // amtZ        — Phase 2 (profile-store)
                0.0,   // geoSpeedKmh — Phase 2 (last-location-store)
                -1.0,  // secsSinceLast — Phase 2; -1 = unknown
                enriched.merchantRiskTier(),
                0, false, 1, // graph features — Phase 2
                txn.channel()
        );
        context.forward(record.withValue(new CheckedTransaction(enriched, signals, fv)));
    }
}
