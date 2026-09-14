package com.fraudgraph.cases.web;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fraudgraph.cases.client.StreamEngineClient;
import com.fraudgraph.cases.model.DecisionTick;
import com.fraudgraph.cases.model.FraudCase;
import com.fraudgraph.cases.service.CaseService;
import com.fraudgraph.cases.store.RecentDecisionStore;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Tool endpoints for the analyst agent (LLD §6.1). The agent gets no database handle and no
 * Kafka client; it reaches every fact through this API. That boundary is the point: an LLM
 * driving tool calls can only ever see what these three endpoints return.
 *
 * <p>Kept separate from {@code /cases} so the split is visible in the routing table, and so a
 * future deployment can put an auth filter or a network policy on {@code /internal} alone.
 */
@RestController
@RequestMapping("/internal")
public class InternalController {
    private static final int MAX_HOURS = 168;   // a week; the decisions topic keeps no more

    private final RecentDecisionStore recent;
    private final StreamEngineClient engine;
    private final CaseService cases;
    private final ObjectMapper mapper;

    public InternalController(RecentDecisionStore recent, StreamEngineClient engine,
                             CaseService cases, ObjectMapper mapper) {
        this.recent = recent;
        this.engine = engine;
        this.cases = cases;
        this.mapper = mapper;
    }

    /**
     * Where the analyst agent writes its finished report. Stored whole as JSONB and never
     * re-parsed here: the report schema belongs to the agent, and validating it twice in two
     * languages is how the two drift apart. The agent's own verify node is the gate.
     */
    @PutMapping("/cases/{caseId}/report")
    public ResponseEntity<FraudCase> attachReport(@PathVariable java.util.UUID caseId,
                                                  @RequestBody Map<String, Object> report) {
        String json;
        try {
            json = mapper.writeValueAsString(report);
        } catch (Exception e) {
            return ResponseEntity.badRequest().build();
        }
        return cases.attachReport(caseId, json)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    /** {@code get_user_history}: recent decisions from Redis plus live profile and window stats. */
    @GetMapping("/users/{userId}/history")
    public Map<String, Object> history(@PathVariable String userId,
                                       @RequestParam(defaultValue = "24") int hours) {
        int bounded = Math.max(1, Math.min(MAX_HOURS, hours));
        List<DecisionTick> ticks = recent.recent(userId, Duration.ofHours(bounded));
        Map<String, Object> out = new HashMap<>();
        out.put("userId", userId);
        out.put("hours", bounded);
        out.put("profile", engine.profile(userId).orElse(null));
        out.put("windows", engine.windows(userId).orElse(null));
        out.put("recent", ticks);
        return out;
    }

    /** {@code get_window_counts}: the live 1m/5m/1h aggregates the velocity check reads. */
    @GetMapping("/users/{userId}/windows")
    public ResponseEntity<Map<String, Object>> windows(@PathVariable String userId) {
        return engine.windows(userId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.status(503).build());
    }

    /** {@code get_graph_neighborhood}: depth is capped at 2 here and again in the engine. */
    @GetMapping("/graph/{userId}/neighborhood")
    public ResponseEntity<Map<String, Object>> neighborhood(@PathVariable String userId,
                                                            @RequestParam(defaultValue = "2") int depth) {
        int bounded = Math.max(1, Math.min(2, depth));
        return engine.neighborhood(userId, bounded)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.status(503).build());
    }
}
