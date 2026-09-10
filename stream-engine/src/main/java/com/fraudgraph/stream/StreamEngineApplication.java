package com.fraudgraph.stream;

import com.fraudgraph.stream.config.FraudGraphProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(FraudGraphProperties.class)
public class StreamEngineApplication {
    public static void main(String[] args) {
        SpringApplication.run(StreamEngineApplication.class, args);
    }
}
