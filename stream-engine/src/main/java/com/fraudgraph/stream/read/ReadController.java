package com.fraudgraph.stream.read;

import com.fraudgraph.stream.check.VelocityWindows;
import com.fraudgraph.stream.check.WindowAggregate;
import com.fraudgraph.stream.config.KafkaStreamsConfig;
import com.fraudgraph.stream.graph.TransactionGraph;
import com.fraudgraph.stream.processor.EnrichProcessor;
import com.fraudgraph.stream.profile.WelfordAccumulator;
import org.apache.kafka.streams.KafkaStreams;
import org.apache.kafka.streams.StoreQueryParameters;
import org.apache.kafka.streams.state.QueryableStoreTypes;
import org.apache.kafka.streams.state.ReadOnlyKeyValueStore;
import org.apache.kafka.streams.state.ReadOnlyWindowStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.util.List;

/**
 * Read-only window into the engine's live state, for the case service and (through it) the
 * analyst agent — LLD §6.1 lists {@code get_window_counts} and {@code get_graph_neighborhood}
 * as backed by "stream-engine read API".
 *
 * <p>Implemented with Kafka Streams interactive queries. Single instance for now, so every key
 * is local; with more instances this would need {@code queryMetadataForKey} plus an RPC hop to
 * the owning instance, which is the documented scale-up path.
 *
 * <p>Nothing here writes, and nothing here is on the decision path.
 */
@RestController
@RequestMapping("/read")
public class ReadController {
    private static final Logger log = LoggerFactory.getLogger(ReadController.class);
    private static final int MAX_DEPTH = 2;   // LLD §6.1 caps the agent's request at 2

    private final KafkaStreamsConfig.StreamsLifecycle lifecycle;
    private final TransactionGraph graph;

    public ReadController(KafkaStreamsConfig.StreamsLifecycle lifecycle, TransactionGraph graph) {
        this.lifecycle = lifecycle;
        this.graph = graph;
    }

    public record Windows(long cnt1m, double sum1m, long cnt5m, double sum5m, long cnt1h, double sum1h) {}

    public record Profile(long n, double mean, double std) {}

    @GetMapping("/users/{userId}/windows")
    public ResponseEntity<Windows> windows(@PathVariable String userId) {
        if (notRunning()) return ResponseEntity.status(503).build();
        long now = System.currentTimeMillis();
        try {
            WindowAggregate a1m = fetch(VelocityWindows.STORE_1M, VelocityWindows.WINDOW_1M, userId, now);
            WindowAggregate a5m = fetch(VelocityWindows.STORE_5M, VelocityWindows.WINDOW_5M, userId, now);
            WindowAggregate a1h = fetch(VelocityWindows.STORE_1H, VelocityWindows.WINDOW_1H, userId, now);
            return ResponseEntity.ok(new Windows(a1m.count(), a1m.sum(), a5m.count(), a5m.sum(), a1h.count(), a1h.sum()));
        } catch (RuntimeException e) {
            log.warn("window read failed for {}: {}", userId, e.toString());
            return ResponseEntity.status(503).build();
        }
    }

    @GetMapping("/users/{userId}/profile")
    public ResponseEntity<Profile> profile(@PathVariable String userId) {
        if (notRunning()) return ResponseEntity.status(503).build();
        try {
            ReadOnlyKeyValueStore<String, WelfordAccumulator> store = lifecycle.streams()
                    .store(StoreQueryParameters.fromNameAndType(EnrichProcessor.PROFILE_STORE, QueryableStoreTypes.keyValueStore()));
            WelfordAccumulator acc = store.get(userId);
            if (acc == null) return ResponseEntity.notFound().build();
            return ResponseEntity.ok(new Profile(acc.n(), round(acc.mean()), round(acc.std())));
        } catch (RuntimeException e) {
            log.warn("profile read failed for {}: {}", userId, e.toString());
            return ResponseEntity.status(503).build();
        }
    }

    /** LLD §6.1 shape: nodes, edges, cycles, componentSize. */
    public record NeighborhoodView(String userId, int depth, List<TransactionGraph.Neighborhood.Node> nodes,
                                   List<TransactionGraph.Neighborhood.Edge> edges, List<List<String>> cycles,
                                   int componentSize) {}

    /** The graph is a plain in-heap bean, not a state store, so this needs no interactive query. */
    @GetMapping("/graph/{userId}/neighborhood")
    public ResponseEntity<NeighborhoodView> neighborhood(
            @PathVariable String userId, @RequestParam(defaultValue = "2") int depth) {
        int bounded = Math.max(1, Math.min(MAX_DEPTH, depth));
        TransactionGraph.Neighborhood n = graph.neighborhood(userId, bounded, System.currentTimeMillis());
        return ResponseEntity.ok(new NeighborhoodView(userId, bounded, n.nodes(), n.edges(), n.cycles(), n.componentSize()));
    }

    private boolean notRunning() {
        return lifecycle.streams().state() != KafkaStreams.State.RUNNING;
    }

    private WindowAggregate fetch(String storeName, Duration window, String userId, long now) {
        ReadOnlyWindowStore<String, WindowAggregate> store = lifecycle.streams()
                .store(StoreQueryParameters.fromNameAndType(storeName, QueryableStoreTypes.windowStore()));
        return VelocityWindows.aggregate(store, window.toMillis(), userId, now);
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
