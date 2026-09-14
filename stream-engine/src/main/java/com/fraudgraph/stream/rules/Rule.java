package com.fraudgraph.stream.rules;

import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.model.Verdict;
import com.fraudgraph.stream.scoring.ScoreResult;

import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Hard rule. Lower priority runs first; the first non-empty verdict wins
 * (chain of responsibility). Rules must never throw.
 *
 * <p>A firing rule returns evidence alongside its verdict, the same way a
 * {@link com.fraudgraph.stream.check.Check} does. Before Phase 5 a rule contributed only its
 * code to {@code firedRules}, which left the analyst agent unable to cite <em>why</em> a
 * transaction was blocked: "sanctioned merchant" with no merchant named is not a citable claim.
 */
public interface Rule {
    String code();

    int priority();

    Optional<Fired> apply(Transaction txn, List<RiskSignal> signals, ScoreResult ml);

    /** A rule that fired: the verdict it demands and the facts behind it. */
    record Fired(Verdict verdict, Map<String, Object> evidence) {
        public Fired {
            evidence = evidence == null ? Map.of() : Map.copyOf(evidence);
        }

        public static Fired of(Verdict verdict, Map<String, Object> evidence) {
            return new Fired(verdict, evidence);
        }
    }
}
