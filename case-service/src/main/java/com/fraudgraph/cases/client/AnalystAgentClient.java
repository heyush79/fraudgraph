package com.fraudgraph.cases.client;

import com.fraudgraph.cases.config.CaseProperties;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.client.RestClient;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;

/**
 * Kicks the analyst agent off for a new case (LLD §5.2: "async, fire-and-forget with retry
 * queue"). The agent is never on the decision path, and it is not even on the case-creation
 * path: a failed hand-off is retried from a bounded in-memory queue and, if it keeps failing,
 * dropped with a counter. A case without a report is still a case an analyst can work.
 *
 * <p>Disabled until the agent exists in Phase 5. The queue is in memory on purpose for v1;
 * making hand-off durable means an outbox table, which is the documented scale-up.
 */
// bean is constructed in HttpClientConfig so the AGENT_STARTED callback can be wired

public class AnalystAgentClient {
    private static final Logger log = LoggerFactory.getLogger(AnalystAgentClient.class);

    private record Attempt(UUID caseId, int attempts) {}

    private final RestClient http;
    private final CaseProperties.Agent cfg;
    private final BlockingQueue<Attempt> queue;
    private final MeterRegistry metrics;
    private final java.util.function.Consumer<UUID> onHandoff;

    public AnalystAgentClient(RestClient agentClient, CaseProperties props, MeterRegistry metrics) {
        this(agentClient, props, metrics, id -> { });
    }

    public AnalystAgentClient(RestClient agentClient, CaseProperties props, MeterRegistry metrics,
                              java.util.function.Consumer<UUID> onHandoff) {
        this.http = agentClient;
        this.cfg = props.agent();
        this.metrics = metrics;
        this.onHandoff = onHandoff;
        this.queue = new ArrayBlockingQueue<>(Math.max(1, cfg.maxQueued()));
        metrics.gauge("fraudgraph_agent_queue_depth", queue, BlockingQueue::size);
    }

    public void investigate(UUID caseId) {
        if (!cfg.enabled()) return;
        if (!queue.offer(new Attempt(caseId, 0))) {
            metrics.counter("fraudgraph_agent_dropped_total").increment();
            log.warn("analyst agent queue full, dropping case {}", caseId);
        }
    }

    @Scheduled(fixedDelay = 1000)
    public void drain() {
        if (!cfg.enabled()) return;
        for (int i = queue.size(); i > 0; i--) {
            Attempt a = queue.poll();
            if (a == null) return;
            try {
                http.post().uri("/investigate").body(Map.of("caseId", a.caseId().toString())).retrieve().toBodilessEntity();
                metrics.counter("fraudgraph_agent_handoff_total", "outcome", "ok").increment();
                onHandoff.accept(a.caseId());
            } catch (Exception e) {
                if (a.attempts() + 1 >= cfg.maxAttempts()) {
                    metrics.counter("fraudgraph_agent_handoff_total", "outcome", "gave_up").increment();
                    log.warn("giving up handing case {} to the analyst agent after {} attempts: {}",
                            a.caseId(), cfg.maxAttempts(), e.toString());
                } else if (!queue.offer(new Attempt(a.caseId(), a.attempts() + 1))) {
                    metrics.counter("fraudgraph_agent_dropped_total").increment();
                }
            }
        }
    }
}
