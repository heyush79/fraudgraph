package com.fraudgraph.stream.scoring;

import com.fraudgraph.scoring.v1.Contribution;
import com.fraudgraph.scoring.v1.ScoringServiceGrpc;
import com.fraudgraph.stream.model.Channel;
import com.fraudgraph.stream.model.FeatureVector;
import io.grpc.ManagedChannel;
import io.grpc.Server;
import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import io.grpc.inprocess.InProcessChannelBuilder;
import io.grpc.inprocess.InProcessServerBuilder;
import io.grpc.stub.StreamObserver;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class GrpcScoringClientTest {
    /**
     * A deadline generous enough that only a genuinely hung call trips it. Tests that are not
     * about the deadline use this: the first gRPC call in a JVM loads a great deal of the
     * stack, and on a shared CI runner that alone can outlast a production-sized 150 ms
     * budget, which failed this class once for reasons that had nothing to do with the code.
     */
    private static final long GENEROUS_MS = 30_000;

    private Server server;
    private ManagedChannel channel;

    /** Fake scorer: returns a canned score after `delayMs`, or fails with the given status. */
    private GrpcScoringClient start(long delayMs, Status failWith, long timeoutMs) throws Exception {
        String name = InProcessServerBuilder.generateName();
        server = InProcessServerBuilder.forName(name).addService(new ScoringServiceGrpc.ScoringServiceImplBase() {
            @Override
            public void score(com.fraudgraph.scoring.v1.FeatureVector req, StreamObserver<com.fraudgraph.scoring.v1.ScoreResult> obs) {
                if (failWith != null) { obs.onError(failWith.asRuntimeException()); return; }
                try { Thread.sleep(delayMs); } catch (InterruptedException ignored) { }
                obs.onNext(com.fraudgraph.scoring.v1.ScoreResult.newBuilder()
                        .setProbability(0.91).setModelVersion("v3")
                        .addContributions(Contribution.newBuilder().setFeature("cnt_1m").setShap(0.31))
                        .addContributions(Contribution.newBuilder().setFeature("in_cycle").setShap(-0.02))
                        .build());
                obs.onCompleted();
            }
        }).build().start();
        channel = InProcessChannelBuilder.forName(name).directExecutor().build();
        return new GrpcScoringClient(channel, timeoutMs);
    }

    @AfterEach
    void tearDown() {
        if (channel != null) channel.shutdownNow();
        if (server != null) server.shutdownNow();
    }

    private static FeatureVector fv() {
        return new FeatureVector("t-1", 9, 12, 30, 5000, 1.2, 0, 40, 2, 0, false, 1, Channel.CARD);
    }

    @Test
    void mapsAScoredResponse() throws Exception {
        ScoreResult r = start(0, null, GENEROUS_MS).score(fv());
        assertThat(r.isScored()).isTrue();
        assertThat(r.probability()).isEqualTo(0.91);
        assertThat(r.modelVersion()).isEqualTo("v3");
        assertThat(r.contributions()).extracting(c -> c.feature()).containsExactly("cnt_1m", "in_cycle");
    }

    @Test
    void deadlineIsEnforced() throws Exception {
        // Warm the stack first, so the measurement below is of the deadline and not of gRPC
        // loading its classes. This is the only test here that asserts on elapsed time.
        start(0, null, GENEROUS_MS).score(fv());
        tearDown();

        long serverDelayMs = 5_000;
        GrpcScoringClient slow = start(serverDelayMs, null, 200);
        long t0 = System.nanoTime();
        assertThatThrownBy(() -> slow.score(fv()))
                .isInstanceOf(StatusRuntimeException.class)
                .satisfies(e -> assertThat(((StatusRuntimeException) e).getStatus().getCode()).isEqualTo(Status.Code.DEADLINE_EXCEEDED));
        long elapsedMs = (System.nanoTime() - t0) / 1_000_000;
        // The claim is that the client gives up long before the server would have answered,
        // which is what stops a slow scorer stalling the stream. Asserting a tight upper
        // bound on a shared runner would only measure the runner.
        assertThat(elapsedMs).isLessThan(serverDelayMs / 2);
    }

    @Test
    void serverErrorsPropagateAsStatus() throws Exception {
        GrpcScoringClient noModel = start(0, Status.FAILED_PRECONDITION.withDescription("no model loaded"), GENEROUS_MS);
        AtomicReference<StatusRuntimeException> caught = new AtomicReference<>();
        try { noModel.score(fv()); } catch (StatusRuntimeException e) { caught.set(e); }
        assertThat(caught.get()).isNotNull();
        assertThat(caught.get().getStatus().getCode()).isEqualTo(Status.Code.FAILED_PRECONDITION);
    }
}
