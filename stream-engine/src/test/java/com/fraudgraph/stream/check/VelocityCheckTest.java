package com.fraudgraph.stream.check;

import com.fraudgraph.stream.Fixtures;
import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.model.RiskSignal;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class VelocityCheckTest {
    private final VelocityCheck check = new VelocityCheck(new FraudGraphProperties.Velocity(8, 20, 60, 30));
    private final com.fraudgraph.stream.model.Transaction txn = Fixtures.txn("u_1", 100.0, Fixtures.T0);

    private static CheckContext ctx(long c1m, long c5m, long c1h) {
        return new CheckContext(new WindowAggregate(c1m, c1m * 10.0), new WindowAggregate(c5m, c5m * 10.0), new WindowAggregate(c1h, c1h * 10.0));
    }

    @Test
    void nothingFiresAtOrBelowTheLimit() {
        assertThat(check.evaluate(txn, ctx(8, 20, 60))).isEmpty();
        assertThat(check.evaluate(txn, ctx(0, 0, 0))).isEmpty();
    }

    @Test
    void oneOverTheLimitFiresWithProportionalSeverity() {
        List<RiskSignal> out = check.evaluate(txn, ctx(9, 9, 9));
        assertThat(out).hasSize(1);
        RiskSignal s = out.get(0);
        assertThat(s.code()).isEqualTo(VelocityCheck.CODE_1M);
        assertThat(s.severity()).isCloseTo(1.0 / 8, org.assertj.core.data.Offset.offset(1e-9));
        assertThat(s.evidence()).containsEntry("count", 9L).containsEntry("limit", 8).containsEntry("windowSecs", 60).containsEntry("sum", 90.0);
    }

    @Test
    void severityIsCappedAtOne() {
        List<RiskSignal> out = check.evaluate(txn, ctx(200, 200, 200));
        assertThat(out).extracting(RiskSignal::code).containsExactly(VelocityCheck.CODE_1M, VelocityCheck.CODE_5M, VelocityCheck.CODE_1H);
        assertThat(out).allSatisfy(s -> assertThat(s.severity()).isEqualTo(1.0));
    }

    @Test
    void neverThrows() {
        assertThat(check.evaluate(txn, null)).isEmpty();
        assertThat(check.evaluate(null, new CheckContext(null, null, null))).isEmpty();
    }
}
