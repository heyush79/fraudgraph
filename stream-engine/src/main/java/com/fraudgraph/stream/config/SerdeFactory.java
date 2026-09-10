package com.fraudgraph.stream.config;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.apache.kafka.common.serialization.Deserializer;
import org.apache.kafka.common.serialization.Serde;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.common.serialization.Serializer;

import java.io.IOException;
import java.io.UncheckedIOException;

/**
 * JSON via Jackson for v1 (debuggable with kcat). Upgrade path: Avro + Schema Registry.
 * One shared, immutable ObjectMapper: Instants as ISO-8601 strings, unknown fields ignored
 * so the generator can add fields before the engine learns about them.
 */
public final class SerdeFactory {
    public static final ObjectMapper MAPPER = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .disable(DeserializationFeature.ADJUST_DATES_TO_CONTEXT_TIME_ZONE);

    private SerdeFactory() {}

    public static <T> Serde<T> json(Class<T> type) {
        return Serdes.serdeFrom(jsonSerializer(), jsonDeserializer(type));
    }

    /** Serializes any object; used for sinks that carry more than one payload type. */
    public static <T> Serializer<T> jsonSerializer() {
        return (topic, data) -> {
            if (data == null) return null;
            try {
                return MAPPER.writeValueAsBytes(data);
            } catch (IOException e) {
                throw new UncheckedIOException(e);
            }
        };
    }

    public static <T> Deserializer<T> jsonDeserializer(Class<T> type) {
        return (topic, bytes) -> {
            if (bytes == null) return null;
            try {
                return MAPPER.readValue(bytes, type);
            } catch (IOException e) {
                // surfaces to the DeserializationExceptionHandler -> DLQ
                throw new UncheckedIOException("cannot deserialize " + type.getSimpleName(), e);
            }
        };
    }
}
