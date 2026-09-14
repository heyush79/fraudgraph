package com.fraudgraph.cases.config;

import com.fraudgraph.cases.feed.FeedHandler;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {
    private final FeedHandler handler;

    public WebSocketConfig(FeedHandler handler) {
        this.handler = handler;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        // Open origins: this is a single-node demo with no auth, and the dashboard is served
        // from a different port in dev and through nginx in compose. Locking this down is part
        // of the same work as adding auth, which the LLD defers.
        registry.addHandler(handler, "/ws/feed").setAllowedOriginPatterns("*");
    }
}
