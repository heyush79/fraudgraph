package com.fraudgraph.stream.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.core.io.ClassPathResource;

import java.io.IOException;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Binds the shipped application.yml exactly as Spring does at startup. Every other test builds
 * FraudGraphProperties in code, so a section that fails to bind (a record Spring cannot
 * construct, a renamed key) passes them all and only surfaces as a crash when the engine
 * starts. That happened once: a convenience constructor on {@code Graph} left the whole
 * section null.
 */
class ConfigBindingTest {

    private FraudGraphProperties bound() throws IOException {
        var env = new StandardEnvironment();
        new YamlPropertySourceLoader().load("application", new ClassPathResource("application.yml"))
                .forEach(env.getPropertySources()::addLast);
        return Binder.get(env).bind("fraudgraph", FraudGraphProperties.class)
                .orElseThrow(() -> new AssertionError("fraudgraph.* did not bind at all"));
    }

    @Test
    void everySectionOfTheShippedConfigBinds() throws IOException {
        FraudGraphProperties p = bound();
        assertThat(p).hasNoNullFieldsOrProperties();
        assertThat(p.kafka()).hasNoNullFieldsOrProperties();
        assertThat(p.scoring().breaker()).isNotNull();
        assertThat(p.rules().sanctionedMerchants()).isNotEmpty();
        assertThat(p.merchantRiskTiers()).isNotEmpty();
    }

    @Test
    void theGraphSectionCarriesThePassThroughSettings() throws IOException {
        FraudGraphProperties.Graph g = bound().graph();
        assertThat(g.maxEdgesPerNode()).isEqualTo(50);
        assertThat(g.maxCycleDepth()).isEqualTo(5);
        assertThat(g.passThroughWindowMins()).isEqualTo(60);
        assertThat(g.passThroughMinRatio()).isEqualTo(0.80);
        assertThat(g.passThroughMaxRatio()).isEqualTo(1.02);
        assertThat(g.passThroughMinDepth()).isEqualTo(1);
    }
}
