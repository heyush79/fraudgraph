package com.fraudgraph.stream.scoring;

import com.fraudgraph.scoring.v1.ScoringServiceGrpc;
import com.fraudgraph.stream.model.Decision;
import com.fraudgraph.stream.model.FeatureVector;
import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Synchronous gRPC call to the Python scorer with a per-call deadline (LLD §3.6: 150 ms).
 * Throws {@link io.grpc.StatusRuntimeException} on timeout/unavailable/precondition — the
 * {@link ResilientScoringClient} wrapping this turns those into breaker failures and DEGRADED
 * results. Never used unwrapped on the hot path.
 */
public final class GrpcScoringClient implements ScoringClient, AutoCloseable {
    private final ManagedChannel channel;
    private final ScoringServiceGrpc.ScoringServiceBlockingStub stub;
    private final long timeoutMs;

    public GrpcScoringClient(String host, int port, long timeoutMs) {
        this(ManagedChannelBuilder.forAddress(host, port).usePlaintext().build(), timeoutMs);
    }

    GrpcScoringClient(ManagedChannel channel, long timeoutMs) {
        this.channel = channel;
        this.stub = ScoringServiceGrpc.newBlockingStub(channel);
        this.timeoutMs = timeoutMs;
    }

    @Override
    public ScoreResult score(FeatureVector fv) {
        com.fraudgraph.scoring.v1.ScoreResult r = stub
                .withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS)
                .score(toProto(fv));
        List<Decision.Contribution> contributions = new ArrayList<>(r.getContributionsCount());
        for (com.fraudgraph.scoring.v1.Contribution c : r.getContributionsList()) {
            contributions.add(new Decision.Contribution(c.getFeature(), c.getShap()));
        }
        return ScoreResult.scored(r.getProbability(), contributions, r.getModelVersion());
    }

    /** Record → wire message, field for field. Guarded by FeatureVectorProtoParityTest. */
    public static com.fraudgraph.scoring.v1.FeatureVector toProto(FeatureVector fv) {
        return com.fraudgraph.scoring.v1.FeatureVector.newBuilder()
                .setTxnId(fv.txnId() == null ? "" : fv.txnId())
                .setCnt1M(fv.cnt1m())
                .setCnt5M(fv.cnt5m())
                .setCnt1H(fv.cnt1h())
                .setSum1H(fv.sum1h())
                .setAmtZ(fv.amtZ())
                .setGeoSpeedKmh(fv.geoSpeedKmh())
                .setSecsSinceLast(fv.secsSinceLast())
                .setMerchantRiskTier(fv.merchantRiskTier())
                .setNodeDegree(fv.nodeDegree())
                .setInCycle(fv.inCycle())
                .setComponentSize(fv.componentSize())
                .setChannel(fv.channel() == null ? 0 : fv.channel().ordinal())
                .build();
    }

    @Override
    public void close() {
        channel.shutdownNow();
    }
}
