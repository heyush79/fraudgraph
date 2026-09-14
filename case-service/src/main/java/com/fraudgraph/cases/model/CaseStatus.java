package com.fraudgraph.cases.model;

import java.util.Set;

/** LLD §5.1 status values, plus the transitions an analyst is allowed to make. */
public enum CaseStatus {
    OPEN,
    INVESTIGATING,
    REPORTED,          // the analyst agent attached a report
    CLOSED_FRAUD,
    CLOSED_FP;         // false positive

    public boolean isClosed() {
        return this == CLOSED_FRAUD || this == CLOSED_FP;
    }

    /**
     * A closed case is terminal: reopening would break the "append-only audit trail" story and
     * the eval harness counts outcomes per case. Everything else can move freely, because a
     * human analyst should not be fought by a state machine.
     */
    public boolean canMoveTo(CaseStatus next) {
        if (next == null || next == this) return false;
        return !isClosed();
    }

    public static Set<CaseStatus> all() {
        return Set.of(values());
    }
}
