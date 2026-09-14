package com.fraudgraph.cases.feed;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fraudgraph.cases.config.CaseProperties;
import com.fraudgraph.cases.model.DecisionTick;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.CopyOnWriteArraySet;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Fans decisions out to the dashboard.
 *
 * <p>At 50 decisions a second, a frame per decision is 50 tiny writes per client per second and
 * a ticker that reads as a blur. Instead ticks are queued and flushed as one JSON array on a
 * fixed interval, so the socket sees ~5 frames a second whatever the traffic.
 *
 * <p>The queue is bounded. A browser that stops reading, or a laptop that sleeps, must not grow
 * the heap: past the cap the oldest ALLOW ticks are dropped first and flagged ones are kept,
 * because losing a blurred ALLOW row costs nothing and losing a BLOCK row costs the demo.
 */
@Component
public class FeedBroadcaster {
    private static final Logger log = LoggerFactory.getLogger(FeedBroadcaster.class);

    private final Set<WebSocketSession> sessions = new CopyOnWriteArraySet<>();
    private final ConcurrentLinkedQueue<DecisionTick> pending = new ConcurrentLinkedQueue<>();
    private final AtomicInteger pendingCount = new AtomicInteger();
    private final Deque<DecisionTick> history = new ArrayDeque<>();

    private final ObjectMapper mapper;
    private final CaseProperties.Feed cfg;
    private final Counter dropped;
    private final Counter sent;

    public FeedBroadcaster(ObjectMapper mapper, CaseProperties props, MeterRegistry metrics) {
        this.mapper = mapper;
        this.cfg = props.feed();
        this.dropped = metrics.counter("fraudgraph_feed_dropped_total");
        this.sent = metrics.counter("fraudgraph_feed_sent_total");
        metrics.gauge("fraudgraph_feed_sessions", sessions, Set::size);
    }

    public void register(WebSocketSession session) {
        sessions.add(session);
        List<DecisionTick> backfill;
        synchronized (history) {
            backfill = new ArrayList<>(history);
        }
        if (!backfill.isEmpty()) {
            send(session, backfill);   // a new tab shows the recent past instead of an empty box
        }
    }

    public void unregister(WebSocketSession session) {
        sessions.remove(session);
    }

    public int sessionCount() {
        return sessions.size();
    }

    public void publish(DecisionTick tick) {
        synchronized (history) {
            history.addLast(tick);
            while (history.size() > cfg.maxHistory()) history.removeFirst();
        }
        if (sessions.isEmpty()) return;      // nobody watching: keep history, skip the queue
        if (pendingCount.get() >= cfg.maxQueued() && !makeRoom()) {
            dropped.increment();
            return;
        }
        pending.add(tick);
        pendingCount.incrementAndGet();
    }

    /** Drops one queued ALLOW to make space for a more interesting tick. */
    private boolean makeRoom() {
        DecisionTick head = pending.peek();
        if (head == null) return true;
        if (head.verdict() != null && head.verdict().createsCase()) return false;
        if (pending.remove(head)) {
            pendingCount.decrementAndGet();
            dropped.increment();
            return true;
        }
        return false;
    }

    /** Flushed by {@link FeedScheduler} on the configured interval. */
    public void flush() {
        if (sessions.isEmpty() || pending.isEmpty()) return;
        List<DecisionTick> batch = new ArrayList<>();
        DecisionTick t;
        while ((t = pending.poll()) != null) {
            pendingCount.decrementAndGet();
            batch.add(t);
        }
        if (batch.isEmpty()) return;
        // Six partitions across two stream threads mean the queue is only loosely ordered.
        // Sorting the batch by event time makes "ticks within a frame are chronological" true,
        // so the ticker does not show 11:27:03.704 above 11:27:03.729.
        batch.sort(java.util.Comparator.comparing(DecisionTick::decidedAt,
                java.util.Comparator.nullsLast(java.util.Comparator.naturalOrder())));
        for (WebSocketSession session : sessions) {
            send(session, batch);
        }
        sent.increment(batch.size());
    }

    private void send(WebSocketSession session, List<DecisionTick> batch) {
        if (!session.isOpen()) {
            sessions.remove(session);
            return;
        }
        try {
            String json = mapper.writeValueAsString(batch);
            synchronized (session) {   // WebSocketSession forbids concurrent sends
                session.sendMessage(new TextMessage(json));
            }
        } catch (IOException | IllegalStateException e) {
            log.debug("dropping feed session {}: {}", session.getId(), e.toString());
            sessions.remove(session);
            try {
                session.close();
            } catch (IOException ignored) {
                // already gone
            }
        } catch (Exception e) {
            log.warn("failed to serialize feed batch", e);
        }
    }
}
