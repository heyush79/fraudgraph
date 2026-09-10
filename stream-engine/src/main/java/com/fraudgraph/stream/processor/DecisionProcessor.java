package com.fraudgraph.stream.processor;

import com.fraudgraph.stream.config.SerdeFactory;
import com.fraudgraph.stream.decision.DecisionAssembler;
import com.fraudgraph.stream.decision.ThresholdPolicy;
import com.fraudgraph.stream.model.CheckedTransaction;
import com.fraudgraph.stream.model.Decision;
import com.fraudgraph.stream.model.DlqRecord;
import com.fraudgraph.stream.model.FeatureVector;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.scoring.ScoreResult;
import com.fraudgraph.stream.scoring.ScoringClient;
import com.fraudgraph.stream.scoring.ShadowSampler;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.apache.kafka.streams.processor.api.Processor;
import org.apache.kafka.streams.processor.api.ProcessorContext;
import org.apache.kafka.streams.processor.api.Record;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Instant;
import java.util.concurrent.TimeUnit;

/**
 * LLD §3.6. Calls the scorer only when a signal fired or the shadow sampler hit, applies the
 * threshold policy, and forwards the Decision to fraud.decisions. Anything that blows up here
 * goes to transactions.dlq with the original payload — the stream never stalls.
 * Output value type is Object because the two sinks carry different payloads.
 */
public final class DecisionProcessor implements Processor<String, CheckedTransaction, String, Object> {
    private static final Logger log = LoggerFactory.getLogger(DecisionProcessor.class);

    public static final String DECISIONS_SINK = "decisions-sink";
    public static final String DLQ_SINK = "dlq-sink";

    private final ScoringClient scoringClient;
    private final ShadowSampler sampler;
    private final ThresholdPolicy policy;
    private final DecisionAssembler assembler;
    private final MeterRegistry metrics;
    private final Timer latency;

    private ProcessorContext<String, Object> context;

    public DecisionProcessor(ScoringClient scoringClient, ShadowSampler sampler, ThresholdPolicy policy,
                             DecisionAssembler assembler, MeterRegistry metrics) {
        this.scoringClient = scoringClient;
        this.sampler = sampler;
        this.policy = policy;
        this.assembler = assembler;
        this.metrics = metrics;
        this.latency = Timer.builder("fraudgraph_decision_latency")
                .publishPercentiles(0.5, 0.95, 0.99)
                .register(metrics);
    }

    @Override
    public void init(ProcessorContext<String, Object> context) {
        this.context = context;
    }

    @Override
    public void process(Record<String, CheckedTransaction> record) {
        CheckedTransaction checked = record.value();
        Transaction txn = checked.enriched().txn();
        try {
            boolean invokeModel = !checked.signals().isEmpty() || sampler.hit(txn.txnId());
            ScoreResult ml = invokeModel ? safeScore(checked.features()) : ScoreResult.notScored();

            ThresholdPolicy.Outcome outcome = policy.decide(txn, checked.signals(), ml);
            Decision decision = assembler.assemble(checked, ml, outcome, System.nanoTime(), Instant.now());

            latency.record(decision.latencyMs(), TimeUnit.MILLISECONDS);
            metrics.counter("fraudgraph_decisions_total", "verdict", decision.verdict().name(), "mode", decision.mode().name()).increment();
            context.forward(record.withValue(decision), DECISIONS_SINK);
        } catch (RuntimeException e) {
            metrics.counter("fraudgraph_dlq_total", "stage", "decision").increment();
            log.error("decision failed for txn {}, routing to DLQ", txn.txnId(), e);
            String payload;
            try {
                payload = SerdeFactory.MAPPER.writeValueAsString(txn);
            } catch (Exception ignored) {
                payload = String.valueOf(txn);
            }
            context.forward(record.withValue(new DlqRecord("decision", e.toString(), payload, Instant.now())), DLQ_SINK);
        }
    }

    private ScoreResult safeScore(FeatureVector fv) {
        try {
            return scoringClient.score(fv);
        } catch (RuntimeException e) {
            log.warn("scoring client threw for txn {}: {}", fv.txnId(), e.toString());
            return ScoreResult.degraded();
        }
    }
}
