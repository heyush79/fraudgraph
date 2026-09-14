package com.fraudgraph.cases.service;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.fraudgraph.cases.model.DecisionDoc;
import com.fraudgraph.cases.model.DecisionTick;
import com.fraudgraph.cases.model.Verdict;
import org.junit.jupiter.api.Test;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/** Parses a decision captured verbatim off the live topic. */
class DecisionDocTest {
    private final ObjectMapper mapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);

    private static final String REAL = """
            {"txnId":"fc7746f4-de85-4b02-b456-c8e3c18a5473","userId":"u_10903","verdict":"BLOCK","mode":"FULL",
             "mlScore":0.9997350573539734,"firedRules":["VELOCITY_1M","VELOCITY_5M"],
             "signals":[{"code":"VELOCITY_1M","severity":1.0,"evidence":{"count":18,"limit":8,"windowSecs":60,"sum":4353.64}}],
             "features":{"cnt1m":18,"channel":"CARD"},
             "contributions":[{"feature":"cnt_1m","shap":7.548951625823975}],
             "latencyMs":25,"decidedAt":"2026-09-12T13:28:17.120558339Z"}
            """;

    @Test
    void parsesALiveDecision() throws Exception {
        DecisionDoc d = mapper.readValue(REAL, DecisionDoc.class);
        assertThat(d.verdict()).isEqualTo(Verdict.BLOCK);
        assertThat(d.mode()).isEqualTo("FULL");
        assertThat(d.mlScore()).isEqualTo(0.9997350573539734);
        assertThat(d.firedRulesOrEmpty()).containsExactly("VELOCITY_1M", "VELOCITY_5M");
        assertThat(d.signals()).singleElement().satisfies(s -> {
            assertThat(s.code()).isEqualTo("VELOCITY_1M");
            assertThat(s.evidence()).containsEntry("count", 18);
        });
        assertThat(d.contributions()).singleElement().satisfies(c -> assertThat(c.feature()).isEqualTo("cnt_1m"));
        assertThat(d.latencyMs()).isEqualTo(25);
        assertThat(d.decidedAt()).isNotNull();
    }

    @Test
    void toleratesAFieldTheEngineAddsLater() throws Exception {
        String withExtra = REAL.replace("\"latencyMs\":25", "\"somethingNew\":{\"a\":1},\"latencyMs\":25");
        assertThat(mapper.readValue(withExtra, DecisionDoc.class).verdict()).isEqualTo(Verdict.BLOCK);
    }

    @Test
    void tickCarriesTheCaseIdForDeepLinking() throws Exception {
        DecisionDoc d = mapper.readValue(REAL, DecisionDoc.class);
        UUID caseId = UUID.randomUUID();
        DecisionTick tick = DecisionTick.of(d, caseId);
        assertThat(tick.caseId()).isEqualTo(caseId);
        assertThat(tick.userId()).isEqualTo("u_10903");
        assertThat(tick.firedRules()).hasSize(2);
        assertThat(mapper.writeValueAsString(tick)).contains("\"verdict\":\"BLOCK\"");
        assertThat(DecisionTick.of(d, null).caseId()).isNull();
    }
}
