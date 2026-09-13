package com.fraudgraph.stream.scoring;

import com.fraudgraph.stream.model.Channel;
import com.fraudgraph.stream.model.FeatureVector;
import com.google.protobuf.Descriptors;
import org.junit.jupiter.api.Test;

import java.lang.reflect.RecordComponent;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Drift guard: the engine's FeatureVector record, the JSON it logs on fraud.decisions and the
 * proto it sends to the scorer must all name the same features. If someone adds a field to
 * scoring.proto and forgets the record (or vice versa), this fails at build time.
 */
class FeatureVectorProtoParityTest {
    static String camel(String snake) {
        String[] parts = snake.split("_");
        StringBuilder sb = new StringBuilder(parts[0]);
        for (int i = 1; i < parts.length; i++) sb.append(Character.toUpperCase(parts[i].charAt(0))).append(parts[i].substring(1));
        return sb.toString();
    }

    @Test
    void recordComponentsMatchProtoFieldsInOrder() {
        List<String> proto = new ArrayList<>();
        for (Descriptors.FieldDescriptor f : com.fraudgraph.scoring.v1.FeatureVector.getDescriptor().getFields()) proto.add(camel(f.getName()));
        List<String> record = new ArrayList<>();
        for (RecordComponent c : FeatureVector.class.getRecordComponents()) record.add(c.getName());
        assertThat(record).containsExactlyElementsOf(proto);
    }

    @Test
    void decisionJsonKeysAreTheProtoFieldsMinusTxnId() {
        FeatureVector fv = sample();
        List<String> expected = new ArrayList<>();
        for (Descriptors.FieldDescriptor f : com.fraudgraph.scoring.v1.FeatureVector.getDescriptor().getFields()) {
            if (!f.getName().equals("txn_id")) expected.add(camel(f.getName()));
        }
        assertThat(fv.asMap().keySet()).containsExactlyElementsOf(expected);
    }

    @Test
    void toProtoCarriesEveryValue() {
        FeatureVector fv = sample();
        var p = GrpcScoringClient.toProto(fv);
        assertThat(p.getTxnId()).isEqualTo("t-1");
        assertThat(p.getCnt1M()).isEqualTo(4);
        assertThat(p.getCnt5M()).isEqualTo(22);
        assertThat(p.getCnt1H()).isEqualTo(71);
        assertThat(p.getSum1H()).isEqualTo(24291.6);
        assertThat(p.getAmtZ()).isEqualTo(3.8);
        assertThat(p.getGeoSpeedKmh()).isEqualTo(79.4);
        assertThat(p.getSecsSinceLast()).isEqualTo(126.7);
        assertThat(p.getMerchantRiskTier()).isEqualTo(1);
        assertThat(p.getNodeDegree()).isEqualTo(2);
        assertThat(p.getInCycle()).isTrue();
        assertThat(p.getComponentSize()).isEqualTo(10);
        assertThat(p.getChannel()).isEqualTo(2); // P2P
        // no proto field left at its default that the record set to something else
        for (Descriptors.FieldDescriptor f : p.getDescriptorForType().getFields()) {
            assertThat(p.hasField(f) || f.getName().equals("txn_id")).as(f.getName()).isTrue();
        }
    }

    static FeatureVector sample() {
        return new FeatureVector("t-1", 4, 22, 71, 24291.6, 3.8, 79.4, 126.7, 1, 2, true, 10, Channel.P2P);
    }
}
