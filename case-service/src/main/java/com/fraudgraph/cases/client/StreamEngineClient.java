package com.fraudgraph.cases.client;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.Map;
import java.util.Optional;

/**
 * Thin client over the engine's read API. Everything returns empty rather than throwing: the
 * engine being unreachable should leave a case detail page missing a panel, not failing.
 */
@Component
public class StreamEngineClient {
    private static final Logger log = LoggerFactory.getLogger(StreamEngineClient.class);

    private final RestClient http;

    public StreamEngineClient(RestClient engineClient) {
        this.http = engineClient;
    }

    public Optional<Map<String, Object>> windows(String userId) {
        return get("/read/users/{id}/windows", userId);
    }

    public Optional<Map<String, Object>> profile(String userId) {
        return get("/read/users/{id}/profile", userId);
    }

    public Optional<Map<String, Object>> neighborhood(String userId, int depth) {
        try {
            return Optional.ofNullable(http.get()
                    .uri("/read/graph/{id}/neighborhood?depth={d}", userId, depth)
                    .retrieve()
                    .body(new org.springframework.core.ParameterizedTypeReference<Map<String, Object>>() {}));
        } catch (Exception e) {
            log.debug("engine neighborhood read failed for {}: {}", userId, e.toString());
            return Optional.empty();
        }
    }

    private Optional<Map<String, Object>> get(String uri, String userId) {
        try {
            return Optional.ofNullable(http.get()
                    .uri(uri, userId)
                    .retrieve()
                    .body(new org.springframework.core.ParameterizedTypeReference<Map<String, Object>>() {}));
        } catch (Exception e) {
            log.debug("engine read {} failed for {}: {}", uri, userId, e.toString());
            return Optional.empty();
        }
    }
}
