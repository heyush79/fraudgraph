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
    public record Outcome(Verdict verdict, Optional<String> ruleCode) {}

    private final FraudGraphProperties.Thresholds thresholds;
    private final RuleEngine rules;

    public ThresholdPolicy(FraudGraphProperties.Thresholds thresholds, RuleEngine rules) {
        this.thresholds = thresholds;
        this.rules = rules;
    }

    public Outcome decide(Transaction txn, List<RiskSignal> signals, ScoreResult ml) {
        Optional<RuleEngine.Outcome> hard = rules.apply(txn, signals, ml);
        if (hard.isPresent()) {
            return new Outcome(hard.get().verdict(), Optional.of(hard.get().ruleCode()));
        }
        if (ml.isScored() && ml.probability() >= thresholds.block()) {
            return new Outcome(Verdict.BLOCK, Optional.empty());
        }
        long strong = signals.stream().filter(s -> s.severity() >= thresholds.minSignalSeverity()).count();
        if ((ml.isScored() && ml.probability() >= thresholds.review()) || strong >= thresholds.minSignalsForReview()) {
            return new Outcome(Verdict.REVIEW, Optional.empty());
        }
        if (ml.isDegraded() && !signals.isEmpty()) {
            return new Outcome(Verdict.REVIEW, Optional.empty());
        }
        return new Outcome(Verdict.ALLOW, Optional.empty());
    }
}
