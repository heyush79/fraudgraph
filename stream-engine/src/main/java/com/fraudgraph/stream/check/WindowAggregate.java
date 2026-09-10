package com.fraudgraph.stream.check;

/** count + sum of amounts. The value type of the velocity window stores and of sliding-window reads. */
public record WindowAggregate(long count, double sum) {
    public static final WindowAggregate EMPTY = new WindowAggregate(0, 0.0);

    public WindowAggregate plus(double amount) {
        return new WindowAggregate(count + 1, sum + amount);
    }

    public WindowAggregate merge(WindowAggregate other) {
        return new WindowAggregate(count + other.count, sum + other.sum);
    }
}
