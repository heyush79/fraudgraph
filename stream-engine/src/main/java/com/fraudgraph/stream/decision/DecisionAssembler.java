package com.fraudgraph.stream.decision;

import com.fraudgraph.stream.model.CheckedTransaction;
import com.fraudgraph.stream.model.Decision;
import com.fraudgraph.stream.model.Mode;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.scoring.ScoreResult;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/** Builds the fraud.decisions event. firedRules = signal codes + the hard rule that fired, if any. */
public final class DecisionAssembler {
    public Decision assemble(CheckedTransaction checked, ScoreResult ml, ThresholdPolicy.Outcome outcome, long nowNanos, Instant decidedAt) {
        List<String> fired = new ArrayList<>();
        for (RiskSignal s : checked.signals()) {
            fired.add(s.code());
        }
        outcome.ruleCode().ifPresent(fired::add);

        long latencyMs = Math.max(0L, (nowNanos - checked.enriched().ingestNanos()) / 1_000_000L);
        var txn = checked.enriched().txn();
        return new Decision(
                txn.txnId(),
                txn.userId(),
                outcome.verdict(),
                ml.isDegraded() ? Mode.DEGRADED : Mode.FULL,
                ml.isScored() ? ml.probability() : null,
                List.copyOf(fired),
                checked.features().asMap(),
                ml.contributions(),
                latencyMs,
                decidedAt
        );
    }
}
