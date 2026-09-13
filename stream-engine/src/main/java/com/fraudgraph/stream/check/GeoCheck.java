package com.fraudgraph.stream.check;

import com.fraudgraph.stream.config.FraudGraphProperties;
import com.fraudgraph.stream.model.RiskSignal;
import com.fraudgraph.stream.model.Transaction;
import com.fraudgraph.stream.profile.LastLocation;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * LLD §3.5 impossible travel. Distance from the last known location; implied speed =
 * km / hours elapsed. Fires {@code GEO_IMPOSSIBLE} when speed > maxSpeedKmh <em>and</em>
 * distance > minDistanceKm (GPS jitter guard). Skips when there is no prior location or the
 * gap is under minGapSecs (division blow-up guard) or negative (out-of-order event).
 */
public final class GeoCheck implements Check {
    private static final Logger log = LoggerFactory.getLogger(GeoCheck.class);
    public static final String CODE = "GEO_IMPOSSIBLE";

    private final FraudGraphProperties.Geo cfg;

    public GeoCheck(FraudGraphProperties.Geo cfg) {
        this.cfg = cfg;
    }

    @Override
    public String name() {
        return "geo";
    }

    @Override
    public List<RiskSignal> evaluate(Transaction txn, CheckContext ctx) {
        try {
            return travel(txn, ctx.lastLocation(), cfg)
                    .filter(t -> t.speedKmh() > cfg.maxSpeedKmh() && t.distanceKm() > cfg.minDistanceKm())
                    .map(t -> {
                        double severity = Math.min(1.0, (t.speedKmh() - cfg.maxSpeedKmh()) / cfg.maxSpeedKmh());
                        Map<String, Object> ev = new LinkedHashMap<>();
                        ev.put("fromLat", ctx.lastLocation().lat());
                        ev.put("fromLon", ctx.lastLocation().lon());
                        ev.put("toLat", txn.lat());
                        ev.put("toLon", txn.lon());
                        ev.put("distanceKm", round1(t.distanceKm()));
                        ev.put("gapSecs", t.gapSecs());
                        ev.put("speedKmh", round1(t.speedKmh()));
                        ev.put("maxSpeedKmh", cfg.maxSpeedKmh());
                        return List.of(new RiskSignal(CODE, severity, ev));
                    })
                    .orElse(List.of());
        } catch (RuntimeException e) {
            log.warn("geo check failed for txn {}: {}", txn == null ? null : txn.txnId(), e.toString());
            return List.of();
        }
    }

    public record Travel(double distanceKm, long gapSecs, double speedKmh) {}

    /** Shared with the feature vector so geoSpeedKmh and the signal agree. Empty when skipped. */
    public static Optional<Travel> travel(Transaction txn, LastLocation last, FraudGraphProperties.Geo cfg) {
        if (txn == null || last == null || txn.ts() == null) return Optional.empty();
        long gapSecs = (txn.ts().toEpochMilli() - last.tsMs()) / 1000;
        if (gapSecs < cfg.minGapSecs()) return Optional.empty();
        double km = GeoMath.haversineKm(last.lat(), last.lon(), txn.lat(), txn.lon());
        double speed = km / (gapSecs / 3600.0);
        return Optional.of(new Travel(km, gapSecs, speed));
    }

    private static double round1(double v) {
        return Math.round(v * 10.0) / 10.0;
    }
}
