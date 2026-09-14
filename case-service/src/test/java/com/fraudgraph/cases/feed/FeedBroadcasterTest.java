package com.fraudgraph.cases.feed;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.fraudgraph.cases.config.CaseProperties;
import com.fraudgraph.cases.model.DecisionTick;
import com.fraudgraph.cases.model.Verdict;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class FeedBroadcasterTest {
    private final ObjectMapper mapper = new ObjectMapper().registerModule(new JavaTimeModule());
    private final SimpleMeterRegistry metrics = new SimpleMeterRegistry();

    private FeedBroadcaster broadcaster(int maxQueued, int maxHistory) {
        var props = new CaseProperties(null, new CaseProperties.Feed(200, maxQueued, maxHistory), null, null, null);
        return new FeedBroadcaster(mapper, props, metrics);
    }

    private static DecisionTick tick(Verdict verdict, String txn) {
        return tick(verdict, txn, Instant.parse("2026-09-13T10:00:00Z"));
    }

    private static DecisionTick tick(Verdict verdict, String txn, Instant at) {
        return new DecisionTick(txn, "u_1", verdict, "FULL", 0.5, List.of(), 7, at, null);
    }

    private static WebSocketSession session(List<String> sink) throws Exception {
        WebSocketSession s = mock(WebSocketSession.class);
        when(s.isOpen()).thenReturn(true);
        when(s.getId()).thenReturn("s1");
        doAnswer(inv -> {
            sink.add(((TextMessage) inv.getArgument(0)).getPayload());
            return null;
        }).when(s).sendMessage(any());
        return s;
    }

    @Test
    void manyTicksBecomeOneFrame() throws Exception {
        List<String> frames = new ArrayList<>();
        FeedBroadcaster b = broadcaster(2000, 200);
        b.register(session(frames));
        frames.clear();                      // ignore the backfill frame
        for (int i = 0; i < 25; i++) b.publish(tick(Verdict.ALLOW, "t" + i));
        b.flush();
        assertThat(frames).hasSize(1);
        assertThat(mapper.readTree(frames.get(0))).hasSize(25);
        b.flush();
        assertThat(frames).hasSize(1);       // nothing queued, nothing sent
    }

    @Test
    void aFullQueueDropsAllowsBeforeFlaggedDecisions() throws Exception {
        List<String> frames = new ArrayList<>();
        FeedBroadcaster b = broadcaster(4, 200);
        b.register(session(frames));
        frames.clear();
        b.publish(tick(Verdict.BLOCK, "block-1"));
        for (int i = 0; i < 3; i++) b.publish(tick(Verdict.ALLOW, "allow-" + i));
        for (int i = 0; i < 10; i++) b.publish(tick(Verdict.ALLOW, "late-" + i));
        b.flush();
        String frame = frames.get(0);
        assertThat(frame).contains("block-1");                      // the interesting one survived
        assertThat(metrics.find("fraudgraph_feed_dropped_total").counter().count()).isGreaterThan(0.0);
        assertThat(mapper.readTree(frame).size()).isLessThanOrEqualTo(4);
    }

    @Test
    void aFrameIsChronologicalEvenWhenPartitionsInterleave() throws Exception {
        List<String> frames = new ArrayList<>();
        FeedBroadcaster b = broadcaster(2000, 200);
        b.register(session(frames));
        frames.clear();
        Instant base = Instant.parse("2026-09-13T10:00:00Z");
        b.publish(tick(Verdict.ALLOW, "late", base.plusMillis(944)));
        b.publish(tick(Verdict.ALLOW, "early", base.plusMillis(704)));
        b.publish(tick(Verdict.ALLOW, "middle", base.plusMillis(875)));
        b.flush();
        var frame = mapper.readTree(frames.get(0));
        assertThat(frame).hasSize(3);
        assertThat(frame.get(0).get("txnId").asText()).isEqualTo("early");
        assertThat(frame.get(2).get("txnId").asText()).isEqualTo("late");
    }

    @Test
    void aNewSessionGetsTheRecentPastImmediately() throws Exception {
        FeedBroadcaster b = broadcaster(2000, 3);
        for (int i = 0; i < 10; i++) b.publish(tick(Verdict.ALLOW, "t" + i));
        List<String> frames = new ArrayList<>();
        b.register(session(frames));
        assertThat(frames).hasSize(1);
        var backfill = mapper.readTree(frames.get(0));
        assertThat(backfill).hasSize(3);                            // capped at maxHistory
        assertThat(backfill.get(2).get("txnId").asText()).isEqualTo("t9");
    }

    @Test
    void aClosedSessionIsDroppedAndNeverRetried() throws Exception {
        WebSocketSession dead = mock(WebSocketSession.class);
        when(dead.isOpen()).thenReturn(false);
        FeedBroadcaster b = broadcaster(2000, 200);
        b.register(dead);
        b.publish(tick(Verdict.ALLOW, "t1"));
        b.flush();
        assertThat(b.sessionCount()).isZero();
    }

    @Test
    void withNobodyWatchingNothingIsQueuedButHistoryStillFills() throws Exception {
        FeedBroadcaster b = broadcaster(2000, 200);
        for (int i = 0; i < 5; i++) b.publish(tick(Verdict.ALLOW, "t" + i));
        List<String> frames = new ArrayList<>();
        b.register(session(frames));
        assertThat(mapper.readTree(frames.get(0))).hasSize(5);
    }
}
