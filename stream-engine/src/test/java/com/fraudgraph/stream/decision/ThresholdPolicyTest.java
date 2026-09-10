package com.fraudgraph.stream.decision;

import com.fraudgraph.stream.Fixtures;
import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.model.Verdict;
import com.fraudgraph.stream.rules.AmountCapRule;
import com.fraudgraph.stream.rules.HardBlockMerchantRule;
import com.fraudgraph.stream.rules.RuleEngine;
import com.fraudgraph.stream.scoring.ScoreResult;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ThresholdPolicyTest {
    private final ThresholdPolicy policy = new ThresholdPolicy(
            new FraudGraphProperties.Thresholds(0.85, 0.60, 2, 0.5),
            new RuleEngine(List.of(new HardBlockMerchantRule(List.of("m_BAD_0001")), new AmountCapRule(200_000))));
    private final Transaction txn = Fixtures.txn("u", 100.0, Fixtures.T0);

    private static RiskSignal sig(String code, double sev) {
        return new RiskSignal(code, sev, Map.of());
    }

    @Test
    void hardRuleBeatsEverything() {
        var out = policy.decide(Fixtures.txn("u", "m_BAD_0001", 1.0, Fixtures.T0), List.of(), ScoreResult.scored(0.01, List.of(), "v1"));
        assertThat(out.verdict()).isEqualTo(Verdict.BLOCK);
        assertThat(out.ruleCode()).contains(HardBlockMerchantRule.CODE);
    }

    @Test
    void mlThresholds() {
        assertThat(policy.decide(txn, List.of(), ScoreResult.scored(0.85, List.of(), "v1")).verdict()).isEqualTo(Verdict.BLOCK);
        assertThat(policy.decide(txn, List.of(), ScoreResult.scored(0.60, List.of(), "v1")).verdict()).isEqualTo(Verdict.REVIEW);
        assertThat(policy.decide(txn, List.of(), ScoreResult.scored(0.59, List.of(), "v1")).verdict()).isEqualTo(Verdict.ALLOW);
    }

    @Test
    void twoStrongSignalsReviewEvenWhenNotScored() {
        var signals = List.of(sig("A", 0.5), sig("B", 0.9));
        assertThat(policy.decide(txn, signals, ScoreResult.notScored()).verdict()).isEqualTo(Verdict.REVIEW);
        assertThat(policy.decide(txn, List.of(sig("A", 0.5), sig("B", 0.49)), ScoreResult.notScored()).verdict()).isEqualTo(Verdict.ALLOW);
    }

    @Test
    void degradedModeReviewsOnAnySignalButNeverBlocks() {
        assertThat(policy.decide(txn, List.of(sig("A", 0.1)), ScoreResult.degraded()).verdict()).isEqualTo(Verdict.REVIEW);
        assertThat(policy.decide(txn, List.of(sig("A", 1.0), sig("B", 1.0), sig("C", 1.0)), ScoreResult.degraded()).verdict()).isEqualTo(Verdict.REVIEW);
        assertThat(policy.decide(txn, List.of(), ScoreResult.degraded()).verdict()).isEqualTo(Verdict.ALLOW);
    }

    @Test
    void cleanTransactionIsAllowed() {
        assertThat(policy.decide(txn, List.of(), ScoreResult.notScored()).verdict()).isEqualTo(Verdict.ALLOW);
    }
}
