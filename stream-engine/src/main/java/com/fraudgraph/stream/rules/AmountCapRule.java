package com.fraudgraph.stream.rules;

import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.model.Verdict;
import com.fraudgraph.stream.scoring.ScoreResult;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
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
    public Optional<Fired> apply(Transaction txn, List<RiskSignal> signals, ScoreResult ml) {
        if (txn.amount() <= capInr) {
            return Optional.empty();
        }
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("amount", txn.amount());
        evidence.put("capInr", capInr);
        evidence.put("currency", txn.currency());
        evidence.put("reason", "amount exceeds the absolute per-transaction cap");
        return Optional.of(Fired.of(Verdict.BLOCK, evidence));
    }
}
