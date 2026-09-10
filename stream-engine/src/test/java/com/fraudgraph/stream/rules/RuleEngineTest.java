package com.fraudgraph.stream.rules;

import com.fraudgraph.stream.Fixtures;
import com.fraudgraph.stream.model.Verdict;
import com.fraudgraph.stream.scoring.ScoreResult;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

class RuleEngineTest {
    private final RuleEngine engine = new RuleEngine(List.of(
            new AmountCapRule(200_000),
            new HardBlockMerchantRule(List.of("m_CRYPTO_0013"))));

    @Test
    void sanctionedMerchantBlocks() {
        var out = engine.apply(Fixtures.txn("u", "m_CRYPTO_0013", 10.0, Fixtures.T0), List.of(), ScoreResult.notScored());
        assertThat(out).contains(new RuleEngine.Outcome(HardBlockMerchantRule.CODE, Verdict.BLOCK));
    }

    @Test
    void amountOverCapBlocks() {
        var out = engine.apply(Fixtures.txn("u", 200_000.01, Fixtures.T0), List.of(), ScoreResult.notScored());
        assertThat(out).contains(new RuleEngine.Outcome(AmountCapRule.CODE, Verdict.BLOCK));
        assertThat(engine.apply(Fixtures.txn("u", 200_000.0, Fixtures.T0), List.of(), ScoreResult.notScored())).isEmpty();
    }

    @Test
    void lowestPriorityRuleWinsAndAThrowingRuleIsSkipped() {
        Rule boom = new Rule() {
            public String code() { return "BOOM"; }
            public int priority() { return -1; }
            public Optional<Verdict> apply(com.fraudgraph.stream.model.Transaction t, List<com.fraudgraph.stream.model.RiskSignal> s, ScoreResult m) { throw new IllegalStateException(); }
        };
        var e = new RuleEngine(List.of(new AmountCapRule(1), boom, new HardBlockMerchantRule(List.of("m_X_0"))));
        var out = e.apply(Fixtures.txn("u", "m_X_0", 5.0, Fixtures.T0), List.of(), ScoreResult.notScored());
        assertThat(out.map(RuleEngine.Outcome::ruleCode)).contains(HardBlockMerchantRule.CODE); // priority 0 beats 10
    }
}
