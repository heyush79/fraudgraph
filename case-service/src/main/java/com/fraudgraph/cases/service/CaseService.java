package com.fraudgraph.cases.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fraudgraph.cases.client.AnalystAgentClient;
import com.fraudgraph.cases.model.CaseEvent;
import com.fraudgraph.cases.model.CaseStatus;
import com.fraudgraph.cases.model.DecisionDoc;
import com.fraudgraph.cases.model.FraudCase;
import com.fraudgraph.cases.store.CaseRepository;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/** Turns a decision into a case, and serves the case API. */
@Service
public class CaseService {
    private static final Logger log = LoggerFactory.getLogger(CaseService.class);

    private final CaseRepository repository;
    private final AnalystAgentClient agent;
    private final ObjectMapper mapper;
    private final MeterRegistry metrics;

    public CaseService(CaseRepository repository, AnalystAgentClient agent, ObjectMapper mapper, MeterRegistry metrics) {
        this.repository = repository;
        this.agent = agent;
        this.mapper = mapper;
        this.metrics = metrics;
    }

    public static class MalformedDecisionException extends RuntimeException {
        public MalformedDecisionException(String message) {
            super(message);
        }
    }

    /**
     * Creates the case for a flagged decision, or returns the id of the one already there.
     * Idempotent by {@code UNIQUE (txn_id)}, so redelivery after a consumer restart is a no-op.
     */
    @Transactional
    public Optional<UUID> recordFlagged(DecisionDoc doc, String rawJson) {
        UUID txnId;
        try {
            txnId = UUID.fromString(doc.txnId());
        } catch (IllegalArgumentException | NullPointerException e) {
            throw new MalformedDecisionException("txnId is not a UUID: " + doc.txnId());
        }
        Optional<UUID> created = repository.insertIfAbsent(txnId, doc.userId(), doc.verdict(), doc.mlScore(), rawJson);
        if (created.isEmpty()) {
            metrics.counter("fraudgraph_cases_duplicate_total").increment();
            return repository.findIdByTxnId(txnId);
        }
        UUID caseId = created.get();
        repository.appendEvent(caseId, CaseEvent.CREATED, payload(Map.of(
                "verdict", doc.verdict().name(),
                "mode", String.valueOf(doc.mode()),
                "firedRules", doc.firedRulesOrEmpty())));
        metrics.counter("fraudgraph_cases_created_total", "verdict", doc.verdict().name()).increment();
        agent.investigate(caseId);
        return Optional.of(caseId);
    }

    public CaseRepository.Page list(CaseStatus status, int limit, int offset) {
        return repository.list(status, limit, offset);
    }

    public Optional<FraudCase> get(UUID caseId) {
        return repository.findById(caseId);
    }

    /** Empty when the case is unknown; throws when the transition itself is not allowed. */
    @Transactional
    public Optional<FraudCase> changeStatus(UUID caseId, CaseStatus next) {
        FraudCase current = repository.findById(caseId).orElse(null);
        if (current == null) return Optional.empty();
        if (!current.status().canMoveTo(next)) {
            throw new IllegalStateException("cannot move a case from " + current.status() + " to " + next);
        }
        repository.appendEvent(caseId, CaseEvent.STATUS_CHANGED,
                payload(Map.of("from", current.status().name(), "to", next.name())));
        return repository.updateStatus(caseId, next);
    }

    /** Empty when the case is unknown. Idempotent: a re-delivered report simply overwrites. */
    @Transactional
    public Optional<FraudCase> attachReport(UUID caseId, String reportJson) {
        if (repository.attachReport(caseId, reportJson) == 0) {
            return Optional.empty();
        }
        repository.appendEvent(caseId, CaseEvent.REPORT_ATTACHED, reportJson);
        metrics.counter("fraudgraph_reports_attached_total").increment();
        return repository.findById(caseId);
    }

    public void recordAgentStarted(UUID caseId) {
        try {
            repository.appendEvent(caseId, CaseEvent.AGENT_STARTED, "{}");
        } catch (RuntimeException e) {
            log.debug("could not record agent start for {}: {}", caseId, e.toString());
        }
    }

    public Map<CaseStatus, Long> countsByStatus() {
        return repository.countsByStatus();
    }

    public Map<String, Long> verdictCountsLastHour() {
        return repository.verdictCountsSince(java.time.Duration.ofHours(1));
    }

    private String payload(Map<String, ?> values) {
        try {
            return mapper.writeValueAsString(values);
        } catch (Exception e) {
            log.warn("could not serialize case event payload", e);
            return "{}";
        }
    }
}
