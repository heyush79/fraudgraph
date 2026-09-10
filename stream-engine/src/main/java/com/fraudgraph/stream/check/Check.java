package com.fraudgraph.stream.check;

import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;

import java.util.List;

/** Pure function of (txn, state). Never throws — returns empty on internal error (LLD §3.3). */
public interface Check {
    String name();

    List<RiskSignal> evaluate(Transaction txn, CheckContext ctx);
}
