package com.fraudgraph.stream.decision;

import com.fraudgraph.stream.model.CheckedTransaction;
import com.fraudgraph.stream.model.Decision;
import com.fraudgraph.stream.model.Mode;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.scoring.ScoreResult;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/**
 * Builds the fraud.decisions event. firedRules = signal codes + the hard rule that fired, if any.
 * latencyMs is end to end (transaction timestamp → decidedAt): it includes the generator's
 * publish, the broker hop and the engine, which is the number a benchmark should report.
 * The engine-only figure is the {@code fraudgraph_engine_latency} timer.
 */
public final class DecisionAssembler {
    public Decision assemble(CheckedTransaction checked, ScoreResult ml, ThresholdPolicy.Outcome outcome, Instant decidedAt) {
        List<String> fired = new ArrayList<>();
        List<RiskSignal> signals = new ArrayList<>(checked.signals());
        for (RiskSignal s : checked.signals()) {
            fired.add(s.code());
        }
        outcome.ruleCode().ifPresent(fired::add);
        outcome.ruleSignal().ifPresent(signals::add);

        var txn = checked.enriched().txn();
        long latencyMs = txn.ts() == null ? 0L : Math.max(0L, decidedAt.toEpochMilli() - txn.ts().toEpochMilli());
        return new Decision(
                txn.txnId(),
                txn.userId(),
                txn.merchantId(),
                txn.merchantCategory(),
                outcome.verdict(),
                ml.isDegraded() ? Mode.DEGRADED : Mode.FULL,
                ml.isScored() ? ml.probability() : null,
                List.copyOf(fired),
                List.copyOf(signals),
                checked.features().asMap(),
                ml.contributions(),
                latencyMs,
                decidedAt
        );
    }
}
