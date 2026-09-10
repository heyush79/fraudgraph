package com.fraudgraph.stream.rules;

import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.model.Verdict;
import com.fraudgraph.stream.scoring.ScoreResult;

import java.util.List;
import java.util.Optional;

/**
 * Hard rule. Lower priority runs first; the first non-empty verdict wins
 * (chain of responsibility). Rules must never throw.
 */
public interface Rule {
    String code();

    int priority();

    Optional<Verdict> apply(Transaction txn, List<RiskSignal> signals, ScoreResult ml);
}
