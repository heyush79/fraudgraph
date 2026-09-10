package com.fraudgraph.stream.check;

import org.apache.kafka.streams.state.WindowStore;
import org.apache.kafka.streams.state.WindowStoreIterator;

import java.time.Duration;

/**
 * Sliding-window counts on top of Kafka Streams WindowStores.
 *
 * <p>A true sliding window can't be kept as one running aggregate (nothing tells you when an
 * event leaves the window), so each store holds fixed-size <em>buckets</em> — 1/60th of its
 * window — keyed by userId and bucket start. "Count in the last N" is the sum of the ≤ 61
 * buckets in (t − N, t]. One store per window, exactly the three from LLD §3.4, each with its
 * own retention = window + grace.
 */
public final class VelocityWindows {
    public static final String STORE_1M = "velocity-1m";
    public static final String STORE_5M = "velocity-5m";
    public static final String STORE_1H = "velocity-1h";

    public static final Duration WINDOW_1M = Duration.ofMinutes(1);
    public static final Duration WINDOW_5M = Duration.ofMinutes(5);
    public static final Duration WINDOW_1H = Duration.ofHours(1);

    public static final int BUCKETS_PER_WINDOW = 60;

    private final WindowStore<String, WindowAggregate> store;
    private final long windowMs;
    private final long bucketMs;

    public VelocityWindows(WindowStore<String, WindowAggregate> store, Duration window) {
        this.store = store;
        this.windowMs = window.toMillis();
        this.bucketMs = bucketSize(window).toMillis();
    }

    public static Duration bucketSize(Duration window) {
        return window.dividedBy(BUCKETS_PER_WINDOW);
    }

    /** Adds the event to its bucket. Call before {@link #aggregate} so the current txn counts. */
    public void record(String userId, double amount, long tsMs) {
        long bucketStart = tsMs - Math.floorMod(tsMs, bucketMs);
        WindowAggregate current = store.fetch(userId, bucketStart);
        store.put(userId, (current == null ? WindowAggregate.EMPTY : current).plus(amount), bucketStart);
    }

    /** Sum of every bucket that starts in (tsMs − window, tsMs]. Never throws. */
    public WindowAggregate aggregate(String userId, long tsMs) {
        long from = tsMs - windowMs + 1;
        WindowAggregate total = WindowAggregate.EMPTY;
        try (WindowStoreIterator<WindowAggregate> it = store.fetch(userId, from, tsMs)) {
            while (it.hasNext()) {
                total = total.merge(it.next().value);
            }
        }
        return total;
    }
}
