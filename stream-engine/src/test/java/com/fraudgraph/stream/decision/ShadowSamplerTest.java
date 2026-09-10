package com.fraudgraph.stream.decision;

import com.fraudgraph.stream.scoring.ShadowSampler;
import org.junit.jupiter.api.Test;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

class ShadowSamplerTest {
    @Test
    void hitsRoughlyAtTheConfiguredRateAndIsDeterministic() {
        ShadowSampler s = new ShadowSampler(0.01);
        int hits = 0;
        for (int i = 0; i < 100_000; i++) {
            String id = UUID.nameUUIDFromBytes(Integer.toString(i).getBytes()).toString();
            boolean h = s.hit(id);
            assertThat(h).isEqualTo(s.hit(id));
            if (h) hits++;
        }
        assertThat(hits).isBetween(700, 1300);
        assertThat(new ShadowSampler(0).hit("x")).isFalse();
        assertThat(new ShadowSampler(1).hit("x")).isTrue();
    }
}
