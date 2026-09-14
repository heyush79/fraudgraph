package com.fraudgraph.cases.store;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fraudgraph.cases.model.CaseEvent;
import com.fraudgraph.cases.model.CaseStatus;
import com.fraudgraph.cases.model.FraudCase;
import com.fraudgraph.cases.model.Verdict;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

@Repository
public class CaseRepository {
    private static final String SUMMARY_COLUMNS =
            "case_id, txn_id, user_id, verdict, ml_score, status, created_at, updated_at, decision_doc->'firedRules' AS fired_rules";

    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public CaseRepository(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    /**
     * LLD §5.1: at-least-once delivery is handled at the database, not in code. A second copy of
     * the same decision conflicts on {@code UNIQUE (txn_id)} and returns no row, so the caller
     * knows it was a duplicate without a read-then-write race.
     */
    public Optional<UUID> insertIfAbsent(UUID txnId, String userId, Verdict verdict, Double mlScore, String decisionDocJson) {
        List<UUID> created = jdbc.query(
                """
                INSERT INTO cases (txn_id, user_id, verdict, ml_score, decision_doc)
                VALUES (?, ?, ?, ?, ?::jsonb)
                ON CONFLICT (txn_id) DO NOTHING
                RETURNING case_id
                """,
                (rs, n) -> rs.getObject("case_id", UUID.class),
                txnId, userId, verdict.name(), mlScore, decisionDocJson);
        return created.stream().findFirst();
    }

    public void appendEvent(UUID caseId, String eventType, String payloadJson) {
        jdbc.update("INSERT INTO case_events (case_id, event_type, payload) VALUES (?, ?, ?::jsonb)",
                caseId, eventType, payloadJson);
    }

    public Optional<FraudCase> findById(UUID caseId) {
        List<FraudCase> found = jdbc.query(
                "SELECT " + SUMMARY_COLUMNS + ", decision_doc::text AS decision_doc_text, report_doc::text AS report_doc_text"
                        + " FROM cases WHERE case_id = ?",
                detailMapper(), caseId);
        if (found.isEmpty()) return Optional.empty();
        FraudCase c = found.get(0);
        return Optional.of(new FraudCase(c.caseId(), c.txnId(), c.userId(), c.verdict(), c.mlScore(), c.status(),
                c.firedRules(), c.createdAt(), c.updatedAt(), c.decisionDoc(), c.reportDoc(), events(caseId)));
    }

    public Optional<UUID> findIdByTxnId(UUID txnId) {
        return jdbc.query("SELECT case_id FROM cases WHERE txn_id = ?",
                (rs, n) -> rs.getObject("case_id", UUID.class), txnId).stream().findFirst();
    }

    public List<CaseEvent> events(UUID caseId) {
        return jdbc.query("SELECT event_type, payload::text AS payload_text, at FROM case_events WHERE case_id = ? ORDER BY at, id",
                (rs, n) -> new CaseEvent(rs.getString("event_type"), rs.getString("payload_text"), instant(rs, "at")),
                caseId);
    }

    public record Page(List<FraudCase> items, long total, int limit, int offset) {}

    public Page list(CaseStatus status, int limit, int offset) {
        String where = status == null ? "" : " WHERE status = ?";
        Object[] args = status == null ? new Object[0] : new Object[]{status.name()};
        Long total = jdbc.queryForObject("SELECT count(*) FROM cases" + where, Long.class, args);

        List<Object> pageArgs = new ArrayList<>(List.of(args));
        pageArgs.add(limit);
        pageArgs.add(offset);
        List<FraudCase> items = jdbc.query(
                "SELECT " + SUMMARY_COLUMNS + " FROM cases" + where + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                summaryMapper(), pageArgs.toArray());
        return new Page(items, total == null ? 0 : total, limit, offset);
    }

    /** Returns empty when the case does not exist; the caller distinguishes that from a rejected transition. */
    public Optional<FraudCase> updateStatus(UUID caseId, CaseStatus next) {
        int rows = jdbc.update("UPDATE cases SET status = ?, updated_at = now() WHERE case_id = ?", next.name(), caseId);
        return rows == 0 ? Optional.empty() : findById(caseId);
    }

    /**
     * Writes the analyst agent's report. Status moves to REPORTED only from an open state: if a
     * human already closed the case, the report still attaches but their verdict stands.
     */
    public int attachReport(UUID caseId, String reportJson) {
        return jdbc.update("""
                UPDATE cases
                   SET report_doc = ?::jsonb,
                       status = CASE WHEN status IN ('OPEN', 'INVESTIGATING') THEN 'REPORTED' ELSE status END,
                       updated_at = now()
                 WHERE case_id = ?
                """, reportJson, caseId);
    }

    public Map<CaseStatus, Long> countsByStatus() {
        Map<CaseStatus, Long> counts = new EnumMap<>(CaseStatus.class);
        for (CaseStatus s : CaseStatus.values()) counts.put(s, 0L);
        jdbc.query("SELECT status, count(*) AS n FROM cases GROUP BY status", rs -> {
            counts.put(CaseStatus.valueOf(rs.getString("status")), rs.getLong("n"));
        });
        return counts;
    }

    public Map<String, Long> verdictCountsSince(java.time.Duration window) {
        Map<String, Long> counts = new java.util.LinkedHashMap<>();
        counts.put("review", 0L);
        counts.put("block", 0L);
        jdbc.query("SELECT verdict, count(*) AS n FROM cases WHERE created_at > now() - (? || ' seconds')::interval GROUP BY verdict",
                rs -> { counts.put(rs.getString("verdict").toLowerCase(), rs.getLong("n")); },
                window.toSeconds());
        return counts;
    }

    // -- mappers ---------------------------------------------------------------

    private RowMapper<FraudCase> summaryMapper() {
        return (rs, n) -> base(rs, null, null, null);
    }

    private RowMapper<FraudCase> detailMapper() {
        return (rs, n) -> base(rs, rs.getString("decision_doc_text"), rs.getString("report_doc_text"), null);
    }

    private FraudCase base(ResultSet rs, String decisionDoc, String reportDoc, List<CaseEvent> events) throws SQLException {
        return new FraudCase(
                rs.getObject("case_id", UUID.class),
                rs.getObject("txn_id", UUID.class),
                rs.getString("user_id"),
                Verdict.valueOf(rs.getString("verdict")),
                (Double) rs.getObject("ml_score"),
                CaseStatus.valueOf(rs.getString("status")),
                firedRules(rs.getString("fired_rules")),
                instant(rs, "created_at"),
                instant(rs, "updated_at"),
                decisionDoc, reportDoc, events);
    }

    private List<String> firedRules(String json) {
        if (json == null || json.isBlank()) return List.of();
        try {
            return mapper.readValue(json, new TypeReference<List<String>>() {});
        } catch (Exception e) {   // a malformed doc must not break the list view
            return List.of();
        }
    }

    private static java.time.Instant instant(ResultSet rs, String column) throws SQLException {
        Timestamp ts = rs.getTimestamp(column);
        return ts == null ? null : ts.toInstant();
    }
}
