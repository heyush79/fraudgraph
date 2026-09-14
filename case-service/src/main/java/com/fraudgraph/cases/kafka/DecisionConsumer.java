package com.fraudgraph.cases.kafka;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fraudgraph.cases.feed.FeedBroadcaster;
import com.fraudgraph.cases.model.DecisionDoc;
import com.fraudgraph.cases.model.DecisionTick;
import com.fraudgraph.cases.service.CaseService;
import com.fraudgraph.cases.store.RecentDecisionStore;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

import java.util.UUID;

/**
 * LLD §5.2. Every decision goes to the live feed and the per-user recent history; only REVIEW
 * and BLOCK become cases.
 *
 * <p>Nothing thrown from here reaches Kafka. A single malformed or unexpected record must not
 * stall a consumer that is keeping up with 50 decisions a second, so failures are counted and
 * logged and the offset moves on. The decisions topic keeps 7 days, so anything skipped can be
 * re-read deliberately.
 */
@Component
public class DecisionConsumer {
    private static final Logger log = LoggerFactory.getLogger(DecisionConsumer.class);

    private final ObjectMapper mapper;
    private final CaseService cases;
    private final FeedBroadcaster feed;
    private final RecentDecisionStore recent;
    private final MeterRegistry metrics;

    public DecisionConsumer(ObjectMapper mapper, CaseService cases, FeedBroadcaster feed,
                            RecentDecisionStore recent, MeterRegistry metrics) {
        this.mapper = mapper;
        this.cases = cases;
        this.feed = feed;
        this.recent = recent;
        this.metrics = metrics;
    }

    @KafkaListener(topics = "${fraudgraph.topics.decisions}", groupId = "${spring.kafka.consumer.group-id}")
    public void onDecision(String json) {
        DecisionDoc doc;
        try {
            doc = mapper.readValue(json, DecisionDoc.class);
        } catch (Exception e) {
            metrics.counter("fraudgraph_decisions_rejected_total", "reason", "unparseable").increment();
            log.warn("skipping unparseable decision: {}", e.toString());
            return;
        }
        if (doc.verdict() == null || doc.txnId() == null || doc.userId() == null) {
            metrics.counter("fraudgraph_decisions_rejected_total", "reason", "incomplete").increment();
            log.warn("skipping decision missing verdict/txnId/userId: {}", doc.txnId());
            return;
        }

        UUID caseId = null;
        if (doc.verdict().createsCase()) {
            try {
                caseId = cases.recordFlagged(doc, json).orElse(null);
            } catch (CaseService.MalformedDecisionException e) {
                metrics.counter("fraudgraph_decisions_rejected_total", "reason", "bad_txn_id").increment();
                log.warn("{}", e.getMessage());
            } catch (Exception e) {
                metrics.counter("fraudgraph_decisions_rejected_total", "reason", "store_failed").increment();
                log.error("could not store case for txn {}", doc.txnId(), e);
            }
        }

        DecisionTick tick = DecisionTick.of(doc, caseId);
        feed.publish(tick);
        recent.record(tick);
        metrics.counter("fraudgraph_decisions_consumed_total", "verdict", doc.verdict().name()).increment();
    }
}
