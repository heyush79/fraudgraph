package com.fraudgraph.cases.model;

public enum Verdict {
    ALLOW, REVIEW, BLOCK;

    /** Only flagged verdicts become cases (LLD §5.2). */
    public boolean createsCase() {
        return this == REVIEW || this == BLOCK;
    }
}
