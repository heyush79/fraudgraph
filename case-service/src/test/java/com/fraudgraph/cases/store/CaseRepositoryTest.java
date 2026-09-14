package com.fraudgraph.cases.store;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fraudgraph.cases.model.CaseEvent;
import com.fraudgraph.cases.model.CaseStatus;
import com.fraudgraph.cases.model.FraudCase;
import com.fraudgraph.cases.model.Verdict;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.junit.jupiter.api.AfterAll;
import org.testcontainers.containers.PostgreSQLContainer;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Real Postgres via Testcontainers (LLD §10), because the behaviour under test is
 * {@code ON CONFLICT DO NOTHING} and JSONB handling, neither of which an in-memory database
 * would reproduce faithfully. Flyway runs the same migration the service ships.
 */
@EnabledIf("databaseAvailable")
class CaseRepositoryTest {
    /**
     * Point the test at a database you started yourself:
     * {@code mvn test -Dfraudgraph.test.jdbcUrl=jdbc:postgresql://localhost:5433/fraudgraph}
     *
     * <p>Testcontainers is the default and is what CI uses. The override exists because Docker
     * Desktop 29's engine API cannot be negotiated by the bundled docker-java client, so on
     * such a machine these tests would otherwise only ever skip, and a test that runs only in
     * CI is a test you cannot debug.
     *
     * <p>The container is started by hand rather than through {@code @Testcontainers}: that
     * extension starts the {@code @Container} field before {@code @EnabledIf} is consulted, so
     * the override could never take effect.
     */
    static final String EXTERNAL_URL = System.getProperty("fraudgraph.test.jdbcUrl");

    static boolean databaseAvailable() {
        if (external()) return true;
        try {
            return org.testcontainers.DockerClientFactory.instance().isDockerAvailable();
        } catch (Throwable t) {
            return false;
        }
    }

    static boolean external() {
        return EXTERNAL_URL != null && !EXTERNAL_URL.isBlank();
    }

    static PostgreSQLContainer<?> postgres;

    static JdbcTemplate jdbc;
    static CaseRepository repository;

    private static final String DOC = """
            {"txnId":"%s","userId":"u_1","verdict":"BLOCK","firedRules":["VELOCITY_1M","GEO_IMPOSSIBLE"],
             "signals":[{"code":"VELOCITY_1M","severity":1.0,"evidence":{"count":18}}]}
            """;

    @BeforeAll
    static void startDatabase() {
        String url, user, pass;
        if (external()) {
            url = EXTERNAL_URL;
            user = System.getProperty("fraudgraph.test.user", "fraudgraph");
            pass = System.getProperty("fraudgraph.test.password", "fraudgraph");
        } else {
            postgres = new PostgreSQLContainer<>("postgres:16-alpine");
            postgres.start();
            url = postgres.getJdbcUrl();
            user = postgres.getUsername();
            pass = postgres.getPassword();
        }
        DriverManagerDataSource ds = new DriverManagerDataSource(url, user, pass);
        ds.setDriverClassName("org.postgresql.Driver");
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
        repository = new CaseRepository(jdbc, new ObjectMapper());
    }

    @AfterAll
    static void stopDatabase() {
        if (postgres != null) postgres.stop();
    }

    @BeforeEach
    void clean() {
        jdbc.update("TRUNCATE case_events, cases CASCADE");
    }

    private Optional<UUID> insert(UUID txnId, Verdict verdict) {
        return repository.insertIfAbsent(txnId, "u_1", verdict, 0.91, DOC.formatted(txnId));
    }

    @Test
    void theSecondCopyOfADecisionCreatesNoSecondCase() {
        UUID txnId = UUID.randomUUID();
        Optional<UUID> first = insert(txnId, Verdict.BLOCK);
        Optional<UUID> second = insert(txnId, Verdict.BLOCK);
        assertThat(first).isPresent();
        assertThat(second).isEmpty();                              // the conflict returns no row
        assertThat(repository.findIdByTxnId(txnId)).contains(first.get());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM cases", Long.class)).isEqualTo(1L);
    }

    @Test
    void storesTheWholeDecisionAndExtractsFiredRules() throws Exception {
        UUID txnId = UUID.randomUUID();
        UUID caseId = insert(txnId, Verdict.BLOCK).orElseThrow();
        FraudCase c = repository.findById(caseId).orElseThrow();
        assertThat(c.txnId()).isEqualTo(txnId);
        assertThat(c.verdict()).isEqualTo(Verdict.BLOCK);
        assertThat(c.status()).isEqualTo(CaseStatus.OPEN);
        assertThat(c.mlScore()).isEqualTo(0.91);
        assertThat(c.firedRules()).containsExactly("VELOCITY_1M", "GEO_IMPOSSIBLE");
        assertThat(c.reportDoc()).isNull();
        assertThat(c.createdAt()).isNotNull();

        // JSONB is lossless as JSON but NOT byte-preserving: Postgres reformats whitespace,
        // reorders object keys and drops duplicates. So the round trip is asserted on the
        // parsed structure, never on the text. Everything downstream parses it as JSON, so
        // this costs nothing; asserting on a substring is what cost an hour of CI.
        JsonNode doc = new ObjectMapper().readTree(c.decisionDoc());
        assertThat(doc.at("/signals/0/severity").asDouble()).isEqualTo(1.0);
        assertThat(doc.at("/signals/0/code").asText()).isEqualTo("VELOCITY_1M");
        assertThat(doc.at("/signals/0/evidence/count").asInt()).isEqualTo(18);
        assertThat(doc.at("/txnId").asText()).isEqualTo(txnId.toString());
    }

    @Test
    void listFiltersByStatusAndPagesNewestFirst() {
        for (int i = 0; i < 5; i++) {
            insert(UUID.randomUUID(), i % 2 == 0 ? Verdict.BLOCK : Verdict.REVIEW);
        }
        CaseRepository.Page all = repository.list(null, 2, 0);
        assertThat(all.total()).isEqualTo(5);
        assertThat(all.items()).hasSize(2);
        assertThat(all.items().get(0).createdAt()).isAfterOrEqualTo(all.items().get(1).createdAt());
        assertThat(all.items().get(0).decisionDoc()).isNull();      // summaries omit the heavy document

        UUID moved = all.items().get(0).caseId();
        repository.updateStatus(moved, CaseStatus.INVESTIGATING);
        assertThat(repository.list(CaseStatus.INVESTIGATING, 10, 0).total()).isEqualTo(1);
        assertThat(repository.list(CaseStatus.OPEN, 10, 0).total()).isEqualTo(4);
        assertThat(repository.list(null, 2, 4).items()).hasSize(1);
    }

    @Test
    void statusUpdateTouchesUpdatedAtAndEventsAreAppendOnly() throws Exception {
        UUID caseId = insert(UUID.randomUUID(), Verdict.REVIEW).orElseThrow();
        repository.appendEvent(caseId, CaseEvent.CREATED, "{\"verdict\":\"REVIEW\"}");
        FraudCase before = repository.findById(caseId).orElseThrow();
        Thread.sleep(10);
        repository.appendEvent(caseId, CaseEvent.STATUS_CHANGED, "{\"from\":\"OPEN\",\"to\":\"CLOSED_FP\"}");
        FraudCase after = repository.updateStatus(caseId, CaseStatus.CLOSED_FP).orElseThrow();

        assertThat(after.status()).isEqualTo(CaseStatus.CLOSED_FP);
        assertThat(after.updatedAt()).isAfter(before.updatedAt());
        List<CaseEvent> events = after.events();
        assertThat(events).extracting(CaseEvent::eventType).containsExactly(CaseEvent.CREATED, CaseEvent.STATUS_CHANGED);
        assertThat(events.get(1).payload()).contains("CLOSED_FP");
    }

    @Test
    void countsPowerTheDashboardHeader() {
        insert(UUID.randomUUID(), Verdict.BLOCK);
        insert(UUID.randomUUID(), Verdict.REVIEW);
        UUID closed = insert(UUID.randomUUID(), Verdict.REVIEW).orElseThrow();
        repository.updateStatus(closed, CaseStatus.CLOSED_FRAUD);

        assertThat(repository.countsByStatus())
                .containsEntry(CaseStatus.OPEN, 2L)
                .containsEntry(CaseStatus.CLOSED_FRAUD, 1L)
                .containsEntry(CaseStatus.REPORTED, 0L);
        assertThat(repository.verdictCountsSince(java.time.Duration.ofHours(1)))
                .containsEntry("block", 1L).containsEntry("review", 2L);
        assertThat(repository.verdictCountsSince(java.time.Duration.ofSeconds(0)).values()).allMatch(n -> n == 0L);
    }

    @Test
    void unknownCaseIsEmptyNotAnError() {
        assertThat(repository.findById(UUID.randomUUID())).isEmpty();
        assertThat(repository.updateStatus(UUID.randomUUID(), CaseStatus.OPEN)).isEmpty();
        assertThat(repository.findIdByTxnId(UUID.randomUUID())).isEmpty();
    }
}
