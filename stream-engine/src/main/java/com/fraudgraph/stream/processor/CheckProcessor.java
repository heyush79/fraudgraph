package com.fraudgraph.stream.processor;

import com.fraudgraph.stream.check.Check;
import com.fraudgraph.stream.check.CheckContext;
import com.fraudgraph.stream.check.GeoCheck;
import com.fraudgraph.stream.check.VelocityWindows;
import com.fraudgraph.stream.check.WindowAggregate;
import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.graph.GraphView;
import com.fraudgraph.stream.graph.TransactionGraph;
import com.fraudgraph.stream.model.CheckedTransaction;
import com.fraudgraph.stream.model.EnrichedTransaction;
import com.fraudgraph.stream.model.FeatureVector;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.profile.LastLocation;
import com.fraudgraph.stream.profile.WelfordAccumulator;
import io.micrometer.core.instrument.MeterRegistry;
import org.apache.kafka.streams.processor.api.Processor;
import org.apache.kafka.streams.processor.api.ProcessorContext;
import org.apache.kafka.streams.processor.api.Record;
import org.apache.kafka.streams.state.KeyValueStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;

/**
 * LLD §3.1 check stage. Order matters and is deliberate:
 * <ol>
 *   <li>velocity windows: write the current txn, then read (it counts against itself)</li>
 *   <li>graph: insert the P2P edge, get the view (the closing edge is what completes a ring)</li>
 *   <li>profile and location: read the <em>prior</em> values (from the enrich stage), run the
 *       checks, and only then write the current txn into them</li>
 * </ol>
 * Checks are isolated: one throwing never stops the others or the stream.
 */
public final class CheckProcessor implements Processor<String, EnrichedTransaction, String, CheckedTransaction> {
    private static final Logger log = LoggerFactory.getLogger(CheckProcessor.class);

    private final List<Check> checks;
    private final TransactionGraph graph;
    private final FraudGraphProperties.Profile profileCfg;
    private final FraudGraphProperties.Geo geoCfg;
    private final MeterRegistry metrics;

    private ProcessorContext<String, CheckedTransaction> context;
    private VelocityWindows w1m;
    private VelocityWindows w5m;
    private VelocityWindows w1h;
    private KeyValueStore<String, WelfordAccumulator> profiles;
    private KeyValueStore<String, LastLocation> locations;

    public CheckProcessor(List<Check> checks, TransactionGraph graph, FraudGraphProperties.Profile profileCfg,
                          FraudGraphProperties.Geo geoCfg, MeterRegistry metrics) {
        this.checks = List.copyOf(checks);
        this.graph = graph;
        this.profileCfg = profileCfg;
        this.geoCfg = geoCfg;
        this.metrics = metrics;
    }

    @Override
    public void init(ProcessorContext<String, CheckedTransaction> context) {
        this.context = context;
        this.w1m = new VelocityWindows(context.getStateStore(VelocityWindows.STORE_1M), VelocityWindows.WINDOW_1M);
        this.w5m = new VelocityWindows(context.getStateStore(VelocityWindows.STORE_5M), VelocityWindows.WINDOW_5M);
        this.w1h = new VelocityWindows(context.getStateStore(VelocityWindows.STORE_1H), VelocityWindows.WINDOW_1H);
        this.profiles = context.getStateStore(EnrichProcessor.PROFILE_STORE);
        this.locations = context.getStateStore(EnrichProcessor.LAST_LOCATION_STORE);
    }

    @Override
    public void process(Record<String, EnrichedTransaction> record) {
        EnrichedTransaction enriched = record.value();
        Transaction txn = enriched.txn();
        long ts = record.timestamp();

        // 1. velocity: write first, then read
        w1m.record(txn.userId(), txn.amount(), ts);
        w5m.record(txn.userId(), txn.amount(), ts);
        w1h.record(txn.userId(), txn.amount(), ts);
        WindowAggregate a1m = w1m.aggregate(txn.userId(), ts);
        WindowAggregate a5m = w5m.aggregate(txn.userId(), ts);
        WindowAggregate a1h = w1h.aggregate(txn.userId(), ts);

        // 2. graph: insert the edge for P2P transfers, otherwise a read-only view
        GraphView gv = txn.counterpartyId() != null
                ? graph.addEdge(txn.userId(), txn.counterpartyId(), txn.amount(), ts)
                : graph.view(txn.userId(), ts);

        // 3. prior profile / location from the enrich stage
        WelfordAccumulator prior = enriched.priorProfile();
        LastLocation last = enriched.lastLocation();
        CheckContext ctx = new CheckContext(a1m, a5m, a1h, prior, last, gv);

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

        // features derived from the same prior state the checks saw
        double amtZ = prior == null ? 0.0 : prior.zScore(txn.amount(), profileCfg.minSamplesForZ(), profileCfg.minStd());
        double secsSinceLast = last == null ? -1.0 : Math.max(0.0, (ts - last.tsMs()) / 1000.0);
        double geoSpeed = GeoCheck.travel(txn, last, geoCfg).map(GeoCheck.Travel::speedKmh).orElse(0.0);

        FeatureVector fv = new FeatureVector(
                txn.txnId(),
                (int) a1m.count(), (int) a5m.count(), (int) a1h.count(), a1h.sum(),
                round2(amtZ), round1(geoSpeed), secsSinceLast,
                enriched.merchantRiskTier(),
                gv.outDegree(), gv.inCycle(), gv.componentSize(),
                txn.channel()
        );

        // 4. now the current txn becomes history
        profiles.put(txn.userId(), (prior == null ? WelfordAccumulator.EMPTY : prior).add(txn.amount()));
        if (last == null || ts >= last.tsMs()) { // never let an out-of-order event move the user back in time
            locations.put(txn.userId(), new LastLocation(txn.lat(), txn.lon(), ts));
        }

        context.forward(record.withValue(new CheckedTransaction(enriched, signals, fv)));
    }

    private static double round1(double v) {
        return Math.round(v * 10.0) / 10.0;
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
