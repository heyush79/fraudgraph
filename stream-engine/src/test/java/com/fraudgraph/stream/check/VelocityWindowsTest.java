package com.fraudgraph.stream.check;

import com.fraudgraph.stream.config.SerdeFactory;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.processor.api.MockProcessorContext;
import org.apache.kafka.streams.state.Stores;
import org.apache.kafka.streams.state.WindowStore;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.Properties;

import static org.assertj.core.api.Assertions.assertThat;

class VelocityWindowsTest {
    private WindowStore<String, WindowAggregate> store;
    private VelocityWindows windows;

    @BeforeEach
    void setUp() {
        Duration window = VelocityWindows.WINDOW_1M;
        store = Stores.windowStoreBuilder(
                Stores.inMemoryWindowStore("velocity-1m", window.plus(Duration.ofSeconds(30)), VelocityWindows.bucketSize(window), false),
                Serdes.String(), SerdeFactory.json(WindowAggregate.class)).withLoggingDisabled().build();
        Properties props = new Properties();
        props.put("application.id", "test");
        props.put("bootstrap.servers", "none:1");
        MockProcessorContext<Object, Object> ctx = new MockProcessorContext<>(props);
        store.init(ctx.getStateStoreContext(), store);
        windows = new VelocityWindows(store, window);
    }

    @AfterEach
    void tearDown() {
        store.close();
    }

    @Test
    void countsOnlyEventsInsideTheSlidingWindow() {
        long t = 1_000_000_000L;
        for (int i = 0; i < 10; i++) {
            windows.record("u", 5.0, t + i * 1_000L); // 10 events over 10 s
        }
        assertThat(windows.aggregate("u", t + 9_000L)).isEqualTo(new WindowAggregate(10, 50.0));
        // 60 s after the first event, the first bucket has just left the window
        assertThat(windows.aggregate("u", t + 60_000L).count()).isEqualTo(9);
        assertThat(windows.aggregate("u", t + 69_000L).count()).isEqualTo(0);
        assertThat(windows.aggregate("other", t + 9_000L)).isEqualTo(WindowAggregate.EMPTY);
    }

    @Test
    void sameBucketAccumulates() {
        long t = 2_000_000_000L;
        windows.record("u", 1.0, t + 100);
        windows.record("u", 2.0, t + 900);
        assertThat(windows.aggregate("u", t + 999)).isEqualTo(new WindowAggregate(2, 3.0));
    }
}
