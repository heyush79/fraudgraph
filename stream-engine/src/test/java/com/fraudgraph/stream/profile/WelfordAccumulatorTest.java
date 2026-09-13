package com.fraudgraph.stream.profile;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class WelfordAccumulatorTest {
    @Test
    void matchesTwoPassMeanAndSampleStd() {
        double[] xs = {120, 80, 200, 95, 110, 130, 90, 300, 105, 115, 125};
        WelfordAccumulator acc = WelfordAccumulator.EMPTY;
        double sum = 0;
        for (double x : xs) { acc = acc.add(x); sum += x; }
        double mean = sum / xs.length;
        double ss = 0;
        for (double x : xs) ss += (x - mean) * (x - mean);
        assertThat(acc.n()).isEqualTo(xs.length);
        assertThat(acc.mean()).isCloseTo(mean, within(1e-9));
        assertThat(acc.std()).isCloseTo(Math.sqrt(ss / (xs.length - 1)), within(1e-9));
    }

    @Test
    void zScoreGuards() {
        WelfordAccumulator few = WelfordAccumulator.EMPTY.add(100).add(200).add(300);
        assertThat(few.zScore(1000, 10, 1.0)).isEqualTo(0.0);          // too few samples
        WelfordAccumulator flat = WelfordAccumulator.EMPTY;
        for (int i = 0; i < 20; i++) flat = flat.add(100);
        assertThat(flat.std()).isCloseTo(0.0, within(1e-9));
        assertThat(flat.zScore(101, 10, 1.0)).isEqualTo(0.0);          // std below epsilon
        WelfordAccumulator ok = WelfordAccumulator.EMPTY;
        for (int i = 0; i < 20; i++) ok = ok.add(i % 2 == 0 ? 90 : 110);
        assertThat(ok.zScore(100, 10, 1.0)).isCloseTo(0.0, within(1e-9));
        assertThat(ok.zScore(200, 10, 1.0)).isGreaterThan(5.0);
        assertThat(WelfordAccumulator.EMPTY.std()).isEqualTo(0.0);
    }
}
