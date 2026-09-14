package com.fraudgraph.stream.rules;

import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.model.Verdict;
import com.fraudgraph.stream.scoring.ScoreResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Comparator;
import java.util.List;
import java.util.Optional;

public final class RuleEngine {
    private static final Logger log = LoggerFactory.getLogger(RuleEngine.class);

    /** The rule that fired, its verdict, and its evidence as a signal the report can cite. */
    public record Outcome(String ruleCode, Verdict verdict, RiskSignal signal) {}

    private final List<Rule> rules;

    public RuleEngine(List<Rule> rules) {
        this.rules = rules.stream().sorted(Comparator.comparingInt(Rule::priority)).toList();
    }

    public Optional<Outcome> apply(Transaction txn, List<RiskSignal> signals, ScoreResult ml) {
        for (Rule rule : rules) {
            try {
                Optional<Rule.Fired> fired = rule.apply(txn, signals, ml);
                if (fired.isPresent()) {
                    // severity 1.0: a hard rule is not a matter of degree
                    RiskSignal signal = new RiskSignal(rule.code(), 1.0, fired.get().evidence());
                    return Optional.of(new Outcome(rule.code(), fired.get().verdict(), signal));
                }
            } catch (RuntimeException e) {
                log.warn("rule {} failed for txn {}: {}", rule.code(), txn.txnId(), e.toString());
            }
        }
        return Optional.empty();
    }
}
