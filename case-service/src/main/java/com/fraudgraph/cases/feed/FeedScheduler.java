package com.fraudgraph.cases.feed;

import com.fraudgraph.cases.config.CaseProperties;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** Drives {@link FeedBroadcaster#flush()} on {@code fraudgraph.feed.flushMillis}. */
@Component
public class FeedScheduler {
    private final FeedBroadcaster broadcaster;

    public FeedScheduler(FeedBroadcaster broadcaster, CaseProperties props) {
        this.broadcaster = broadcaster;
    }

    @Scheduled(fixedDelayString = "${fraudgraph.feed.flushMillis}")
    public void flush() {
        broadcaster.flush();
    }
}
