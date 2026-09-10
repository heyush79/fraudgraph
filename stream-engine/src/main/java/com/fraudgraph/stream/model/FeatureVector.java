package com.fraudgraph.stream.model;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Mirrors {@code proto/scoring.proto} FeatureVector field-for-field. In Phase 3 this record is
 * replaced by the generated proto class; until then it is the contract the checks fill in.
 * Fields that Phase 2 populates carry their "not yet known" defaults here.
 */
public record FeatureVector(
        String txnId,
        int cnt1m,
        int cnt5m,
        int cnt1h,
        double sum1h,
        double amtZ,
        double geoSpeedKmh,
        double secsSinceLast,
        int merchantRiskTier,
        int nodeDegree,
        boolean inCycle,
        int componentSize,
        Channel channel
) {
    /** Insertion-ordered so the JSON on fraud.decisions is stable and diffable. */
    public Map<String, Object> asMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("cnt1m", cnt1m);
        m.put("cnt5m", cnt5m);
        m.put("cnt1h", cnt1h);
        m.put("sum1h", sum1h);
        m.put("amtZ", amtZ);
        m.put("geoSpeedKmh", geoSpeedKmh);
        m.put("secsSinceLast", secsSinceLast);
        m.put("merchantRiskTier", merchantRiskTier);
        m.put("nodeDegree", nodeDegree);
        m.put("inCycle", inCycle);
        m.put("componentSize", componentSize);
        m.put("channel", channel == null ? null : channel.name());
        return m;
    }
}
