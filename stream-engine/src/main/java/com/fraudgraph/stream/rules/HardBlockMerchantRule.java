package com.fraudgraph.stream.rules;

import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.model.Verdict;
import com.fraudgraph.stream.scoring.ScoreResult;

import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/** Sanctioned / blocklisted merchant → BLOCK, regardless of score or mode. */
public final class HardBlockMerchantRule implements Rule {
    public static final String CODE = "HARD_BLOCK_MERCHANT";

    private final Set<String> sanctioned;

    public HardBlockMerchantRule(Collection<String> sanctioned) {
        this.sanctioned = Set.copyOf(sanctioned);
    }

    @Override
    public String code() {
        return CODE;
    }

    @Override
    public int priority() {
        return 0;
    }

    @Override
    public Optional<Fired> apply(Transaction txn, List<RiskSignal> signals, ScoreResult ml) {
        if (txn.merchantId() == null || !sanctioned.contains(txn.merchantId())) {
            return Optional.empty();
        }
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("merchantId", txn.merchantId());
        evidence.put("merchantCategory", txn.merchantCategory());
        evidence.put("reason", "merchant is on the sanctions blocklist");
        return Optional.of(Fired.of(Verdict.BLOCK, evidence));
    }
}
