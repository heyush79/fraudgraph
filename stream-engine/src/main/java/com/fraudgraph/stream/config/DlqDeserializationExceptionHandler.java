package com.fraudgraph.stream.config;

import com.fraudgraph.stream.model.DlqRecord;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.Producer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.ByteArraySerializer;
import org.apache.kafka.streams.StreamsConfig;
import org.apache.kafka.streams.errors.DeserializationExceptionHandler;
import org.apache.kafka.streams.processor.ProcessorContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * Poison messages (LLD §3.7): raw bytes + error → transactions.dlq, then CONTINUE.
 * Uses its own plain producer because the Streams transactional producer isn't reachable
 * from a deserialization handler; a DLQ write is best-effort and outside the EOS transaction.
 */
public final class DlqDeserializationExceptionHandler implements DeserializationExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(DlqDeserializationExceptionHandler.class);
    public static final String DLQ_TOPIC_CONFIG = "fraudgraph.dlq.topic";

    private String dlqTopic = "transactions.dlq";
    private Producer<byte[], byte[]> producer;

    @Override
    public void configure(Map<String, ?> configs) {
        Object topic = configs.get(DLQ_TOPIC_CONFIG);
        if (topic != null) dlqTopic = topic.toString();
        Object bootstrap = configs.get(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG);
        if (bootstrap != null) {
            Map<String, Object> props = new HashMap<>();
            props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
            props.put(ProducerConfig.CLIENT_ID_CONFIG, "fraudgraph-dlq");
            props.put(ProducerConfig.ACKS_CONFIG, "all");
            producer = new KafkaProducer<>(props, new ByteArraySerializer(), new ByteArraySerializer());
        }
    }

    @Override
    public DeserializationHandlerResponse handle(ProcessorContext context, ConsumerRecord<byte[], byte[]> record, Exception exception) {
        String payload = record.value() == null ? null : new String(record.value(), StandardCharsets.UTF_8);
        log.warn("poison record on {}-{}@{}: {}", record.topic(), record.partition(), record.offset(), exception.toString());
        if (producer != null) {
            try {
                DlqRecord dlq = new DlqRecord("deserialize", exception.toString(), payload, Instant.now());
                byte[] value = SerdeFactory.MAPPER.writeValueAsBytes(dlq);
                producer.send(new ProducerRecord<>(dlqTopic, record.key(), value));
            } catch (Exception e) {
                log.error("failed to write poison record to DLQ", e);
            }
        }
        return DeserializationHandlerResponse.CONTINUE;
    }
}
