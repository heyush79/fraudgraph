package com.fraudgraph.stream.check;

import com.fraudgraph.stream.graph.GraphView;
import com.fraudgraph.stream.profile.LastLocation;
import com.fraudgraph.stream.profile.WelfordAccumulator;

/**
 * Everything a check may read, fetched once per transaction by the CheckProcessor so the
 * checks themselves stay pure and trivially testable.
 *
 * @param last1m/last5m/last1h velocity aggregates including the current txn
 * @param priorProfile amount statistics before this txn (null on first sight)
 * @param lastLocation where the user last transacted before this txn (null on first sight)
 * @param graph graph view after this txn's edge (if P2P) was inserted
 */
public record CheckContext(WindowAggregate last1m, WindowAggregate last5m, WindowAggregate last1h,
                           WelfordAccumulator priorProfile, LastLocation lastLocation, GraphView graph) {
    /** Phase 1 shape, still used by velocity tests. */
    public CheckContext(WindowAggregate last1m, WindowAggregate last5m, WindowAggregate last1h) {
        this(last1m, last5m, last1h, null, null, GraphView.NONE);
    }
}
