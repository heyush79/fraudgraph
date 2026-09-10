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

    public record Outcome(String ruleCode, Verdict verdict) {}

    private final List<Rule> rules;

    public RuleEngine(List<Rule> rules) {
        this.rules = rules.stream().sorted(Comparator.comparingInt(Rule::priority)).toList();
    }

    public Optional<Outcome> apply(Transaction txn, List<RiskSignal> signals, ScoreResult ml) {
        for (Rule rule : rules) {
            try {
                Optional<Verdict> v = rule.apply(txn, signals, ml);
                if (v.isPresent()) {
                    return Optional.of(new Outcome(rule.code(), v.get()));
                }
            } catch (RuntimeException e) {
                log.warn("rule {} failed for txn {}: {}", rule.code(), txn.txnId(), e.toString());
            }
        }
        return Optional.empty();
    }
}
