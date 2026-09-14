package com.fraudgraph.cases.store;

import com.fraudgraph.cases.config.CaseProperties;
import com.fraudgraph.cases.model.DecisionTick;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;

/**
 * The one place Redis is used (LLD §3.4: "Redis is used only for cross-service reads"). The
 * engine's hot path never touches it. It holds a capped, expiring list of each user's recent
 * decisions so the analyst agent's {@code get_user_history} tool has something to read without
 * putting all 50 decisions a second into Postgres.
 *
 * <p>Every method swallows Redis failures: a missing history degrades the agent's context, it
 * must never break case creation or the live feed.
 */
@Component
public class RecentDecisionStore {
    private static final Logger log = LoggerFactory.getLogger(RecentDecisionStore.class);
    private static final String PREFIX = "fg:recent:";

    private final StringRedisTemplate redis;
    private final CaseProperties.Recent cfg;
    private final com.fasterxml.jackson.databind.ObjectMapper mapper;
    private volatile boolean warned;

    public RecentDecisionStore(StringRedisTemplate redis, CaseProperties props,
                               com.fasterxml.jackson.databind.ObjectMapper mapper) {
        this.redis = redis;
        this.cfg = props.recent();
        this.mapper = mapper;
    }

    public void record(DecisionTick tick) {
        if (!cfg.enabled()) return;
        try {
            String key = PREFIX + tick.userId();
            redis.opsForList().leftPush(key, mapper.writeValueAsString(tick));
            redis.opsForList().trim(key, 0, cfg.perUser() - 1);
            redis.expire(key, Duration.ofHours(cfg.ttlHours()));
        } catch (Exception e) {
            warnOnce(e);
        }
    }

    /** Newest first, at most {@code perUser} entries, filtered to the requested window. */
    public List<DecisionTick> recent(String userId, Duration window) {
        if (!cfg.enabled()) return List.of();
        try {
            List<String> raw = redis.opsForList().range(PREFIX + userId, 0, cfg.perUser() - 1);
            if (raw == null) return List.of();
            java.time.Instant cutoff = java.time.Instant.now().minus(window);
            List<DecisionTick> out = new java.util.ArrayList<>(raw.size());
            for (String s : raw) {
                DecisionTick t = mapper.readValue(s, DecisionTick.class);
                if (t.decidedAt() == null || t.decidedAt().isAfter(cutoff)) out.add(t);
            }
            return out;
        } catch (Exception e) {
            warnOnce(e);
            return List.of();
        }
    }

    private void warnOnce(Exception e) {
        if (!warned) {
            warned = true;
            log.warn("Redis unavailable, recent-decision history is disabled for now: {}", e.toString());
        }
    }
}
