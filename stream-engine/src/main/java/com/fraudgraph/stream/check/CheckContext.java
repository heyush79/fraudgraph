package com.fraudgraph.stream.check;

/**
 * Everything a check may read, fetched once per transaction by the CheckProcessor so the
 * checks themselves stay pure and trivially testable. Phase 2 adds profile, last location
 * and graph views here.
 */
public record CheckContext(WindowAggregate last1m, WindowAggregate last5m, WindowAggregate last1h) {}
