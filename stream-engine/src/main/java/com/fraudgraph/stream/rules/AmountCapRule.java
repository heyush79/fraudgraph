package com.fraudgraph.stream.rules;

import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.model.Verdict;
import com.fraudgraph.stream.scoring.ScoreResult;

import java.util.List;
import java.util.Optional;

/** Amount above the absolute cap → BLOCK. Manual approval flow territory, never auto-allow. */
public final class AmountCapRule implements Rule {
    public static final String CODE = "AMOUNT_CAP";

    private final double capInr;

    public AmountCapRule(double capInr) {
        this.capInr = capInr;
    }

    @Override
    public String code() {
        return CODE;
    }

    @Override
    public int priority() {
        return 10;
    }

    @Override
    public Optional<Verdict> apply(Transaction txn, List<RiskSignal> signals, ScoreResult ml) {
        return txn.amount() > capInr ? Optional.of(Verdict.BLOCK) : Optional.empty();
    }
}
