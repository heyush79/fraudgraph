package com.fraudgraph.stream.decision;

import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.model.Verdict;
import com.fraudgraph.stream.rules.RuleEngine;
import com.fraudgraph.stream.scoring.ScoreResult;

import java.util.List;
import java.util.Optional;

/**
 * LLD §3.6 decision table, first match wins:
 * <ol>
 *   <li>any hard rule fires → BLOCK</li>
 *   <li>mlScore ≥ block → BLOCK</li>
 *   <li>mlScore ≥ review, or ≥ minSignalsForReview signals with severity ≥ minSignalSeverity → REVIEW</li>
 *   <li>scorer DEGRADED and ≥ 1 signal → REVIEW (never auto-block on rules alone in degraded mode)</li>
 *   <li>otherwise → ALLOW</li>
 * </ol>
 */
public final class ThresholdPolicy {
    /** {@code ruleSignal} is present only when a hard rule fired, and carries its evidence. */
    public record Outcome(Verdict verdict, Optional<String> ruleCode, Optional<RiskSignal> ruleSignal) {
        static Outcome of(Verdict verdict) {
            return new Outcome(verdict, Optional.empty(), Optional.empty());
        }
    }

    private final FraudGraphProperties.Thresholds thresholds;
    private final RuleEngine rules;

    public ThresholdPolicy(FraudGraphProperties.Thresholds thresholds, RuleEngine rules) {
        this.thresholds = thresholds;
        this.rules = rules;
    }

    public Outcome decide(Transaction txn, List<RiskSignal> signals, ScoreResult ml) {
        Optional<RuleEngine.Outcome> hard = rules.apply(txn, signals, ml);
        if (hard.isPresent()) {
            RuleEngine.Outcome o = hard.get();
            return new Outcome(o.verdict(), Optional.of(o.ruleCode()), Optional.of(o.signal()));
        }
        if (ml.isScored() && ml.probability() >= thresholds.block()) {
            return Outcome.of(Verdict.BLOCK);
        }
        long strong = signals.stream().filter(s -> s.severity() >= thresholds.minSignalSeverity()).count();
        if ((ml.isScored() && ml.probability() >= thresholds.review()) || strong >= thresholds.minSignalsForReview()) {
            return Outcome.of(Verdict.REVIEW);
        }
        if (ml.isDegraded() && !signals.isEmpty()) {
            return Outcome.of(Verdict.REVIEW);
        }
        return Outcome.of(Verdict.ALLOW);
    }
}
