package com.fraudgraph.cases.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Everything tunable, bound from {@code fraudgraph.*}; each number is justified in application.yml. */
@ConfigurationProperties(prefix = "fraudgraph")
public record CaseProperties(Topics topics, Feed feed, Recent recent, Engine engine, Agent agent) {
    public record Topics(String decisions) {}

    public record Feed(long flushMillis, int maxQueued, int maxHistory) {}

    public record Recent(boolean enabled, int perUser, int ttlHours) {}

    public record Engine(String baseUrl, int timeoutMillis) {}

    public record Agent(boolean enabled, String baseUrl, int timeoutMillis, int maxQueued, int maxAttempts) {}
}
