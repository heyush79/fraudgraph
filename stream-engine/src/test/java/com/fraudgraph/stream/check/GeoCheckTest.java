package com.fraudgraph.stream.check;

import com.fraudgraph.stream.Fixtures;
import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.graph.GraphView;
import com.fraudgraph.stream.model.Channel;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.profile.LastLocation;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class GeoCheckTest {
    private static final double HYD_LAT = 17.3850, HYD_LON = 78.4867;
    private static final double DEL_LAT = 28.6139, DEL_LON = 77.2090;   // ~1253 km from Hyderabad
    private final GeoCheck check = new GeoCheck(new FraudGraphProperties.Geo(900, 100, 60));

    private static Transaction at(double lat, double lon, Instant ts) {
        return new Transaction("t", "u", "m_GROC_0001", null, 100, "INR", lat, lon, "d", Channel.CARD, ts);
    }

    private static CheckContext ctx(LastLocation last) {
        return new CheckContext(WindowAggregate.EMPTY, WindowAggregate.EMPTY, WindowAggregate.EMPTY, null, last, GraphView.NONE);
    }

    @Test
    void haversineHyderabadDelhi() {
        assertThat(GeoMath.haversineKm(HYD_LAT, HYD_LON, DEL_LAT, DEL_LON)).isCloseTo(1253, within(15.0));
    }

    @Test
    void firstTransactionHasNoPriorLocation() {
        assertThat(check.evaluate(at(DEL_LAT, DEL_LON, Fixtures.T0), ctx(null))).isEmpty();
    }

    @Test
    void impossibleTravelFiresWithEvidence() {
        LastLocation last = new LastLocation(HYD_LAT, HYD_LON, Fixtures.T0.toEpochMilli());
        List<RiskSignal> out = check.evaluate(at(DEL_LAT, DEL_LON, Fixtures.T0.plusSeconds(300)), ctx(last));
        assertThat(out).hasSize(1);
        RiskSignal s = out.get(0);
        assertThat(s.code()).isEqualTo(GeoCheck.CODE);
        assertThat(s.severity()).isEqualTo(1.0); // 1253 km in 5 min ≈ 15,000 km/h
        assertThat(s.evidence()).containsEntry("gapSecs", 300L).containsKeys("distanceKm", "speedKmh", "fromLat", "toLon");
        assertThat((double) s.evidence().get("distanceKm")).isCloseTo(1253, within(15.0));
    }

    @Test
    void gapUnderMinimumIsSkippedEvenWhenFar() {
        LastLocation last = new LastLocation(HYD_LAT, HYD_LON, Fixtures.T0.toEpochMilli());
        assertThat(check.evaluate(at(DEL_LAT, DEL_LON, Fixtures.T0), ctx(last))).isEmpty();               // Δt = 0
        assertThat(check.evaluate(at(DEL_LAT, DEL_LON, Fixtures.T0.plusSeconds(59)), ctx(last))).isEmpty(); // Δt < 60
        assertThat(check.evaluate(at(DEL_LAT, DEL_LON, Fixtures.T0.minusSeconds(600)), ctx(last))).isEmpty(); // out of order
    }

    @Test
    void gpsJitterNeverFires() {
        // 2 km apart, 61 s apart → 118 km/h, distance under 100 km either way
        LastLocation last = new LastLocation(HYD_LAT, HYD_LON, Fixtures.T0.toEpochMilli());
        assertThat(check.evaluate(at(HYD_LAT + 0.018, HYD_LON, Fixtures.T0.plusSeconds(61)), ctx(last))).isEmpty();
        // 50 km in 61 s is 2950 km/h but under the distance floor: still no signal
        assertThat(check.evaluate(at(HYD_LAT + 0.45, HYD_LON, Fixtures.T0.plusSeconds(61)), ctx(last))).isEmpty();
    }

    @Test
    void plausibleFlightDoesNotFire() {
        // Hyderabad → Delhi in 2 hours ≈ 627 km/h
        LastLocation last = new LastLocation(HYD_LAT, HYD_LON, Fixtures.T0.toEpochMilli());
        assertThat(check.evaluate(at(DEL_LAT, DEL_LON, Fixtures.T0.plusSeconds(7200)), ctx(last))).isEmpty();
    }
}
