package com.fraudgraph.cases.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.time.Duration;

@Configuration
public class HttpClientConfig {
    /** Talks to the stream engine's read API. Short timeouts: a slow engine must not hang a request. */
    @Bean
    public RestClient engineClient(CaseProperties props) {
        return RestClient.builder()
                .baseUrl(props.engine().baseUrl())
                .requestFactory(factory(props.engine().timeoutMillis()))
                .build();
    }

    @Bean
    public RestClient agentClient(CaseProperties props) {
        return RestClient.builder()
                .baseUrl(props.agent().baseUrl())
                .requestFactory(factory(props.agent().timeoutMillis()))
                .build();
    }

    /**
     * Built here rather than annotated so the AGENT_STARTED callback can be injected lazily:
     * CaseService needs the client and the client needs to write to CaseService.
     */
    @Bean
    public com.fraudgraph.cases.client.AnalystAgentClient analystAgentClient(
            RestClient agentClient, CaseProperties props, io.micrometer.core.instrument.MeterRegistry metrics,
            org.springframework.beans.factory.ObjectProvider<com.fraudgraph.cases.service.CaseService> cases) {
        return new com.fraudgraph.cases.client.AnalystAgentClient(agentClient, props, metrics,
                caseId -> cases.getObject().recordAgentStarted(caseId));
    }

    private static SimpleClientHttpRequestFactory factory(int timeoutMillis) {
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(Duration.ofMillis(timeoutMillis));
        f.setReadTimeout(Duration.ofMillis(timeoutMillis));
        return f;
    }
}
