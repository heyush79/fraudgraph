# FraudGraph: 2-minute demo video

A shot list and voiceover for recording the demo yourself. Target length 2:00; every section
has a hard stop so the whole thing stays under 2:15.

## Before recording

- **Stack:** `make demo`, wait two minutes for traffic to build up, then open
  `http://localhost:3000` in a clean browser window (no bookmarks bar, 110% zoom, dark theme).
  Live mode is better than the replay for the video: the numbers in the header are real and
  the scenario lands while you watch.
- **Terminal:** a second window, font 16pt or larger, in the repo root. You will type one
  command: `make scenario-ring`.
- **Check the analyst** answers before you start: open any flagged case and ask "Why was this
  transaction flagged?" once. The first answer also warms the cache.
- **Recorder:** macOS `Cmd+Shift+5`, record the selected portion, 1920×1080. Record the
  voiceover separately if you like; the timings below leave room for it.

## Shots

**0:00–0:12 · The hook** (console, feed scrolling)

> "This is FraudGraph. Every payment in this stream gets a verdict, allow, review or block,
> in about eight milliseconds. And every flagged payment gets investigated by an AI analyst
> that is not allowed to make anything up."

Point at the header: decisions per second, p50 and p99 latency.

**0:12–0:40 · Plant a ring** (terminal, then console)

Run `make scenario-ring`. Switch to the console, click **Flagged** in the feed.

> "I've just planted a money-laundering ring: five accounts passing money in a circle, each
> keeping a small cut. Watch the flagged column. The first transfer looks normal, so it's
> allowed. From the second one on, the engine sees an account forwarding money it received a
> few seconds earlier, and flags it. The last transfer closes the loop, and it's blocked."

Click the BLOCK row for the ring.

**0:40–1:05 · The case** (case investigation pane)

Scroll slowly: *Why it was flagged* → the account chips of the ring → model score.

> "Here's why: the signals in plain words, the ring itself, account by account, and the
> model's score with the features that pushed it. The model only runs when a rule fires, which
> keeps latency down, and I measured what that costs: before I added the pass-through check,
> production caught 7% of ring transfers. Now it catches most of them."

**1:05–1:40 · Ask the analyst** (chat pane)

Click the suggested question **"Where did the money come from, and where did it go?"**
Wait for the answer. Hover a citation chip.

> "Now the AI part. I can ask questions about the case. Every sentence cites the evidence it
> comes from, and before I see the answer, code checks that every number in it really is in
> that evidence."

Ask **"What evidence would change the verdict?"**. If the answer shows *The verifier removed
N unsupported claims*, expand it.

> "And when the model writes a number it can't support, like a rate it worked out itself,
> the verifier removes the sentence and shows me why. It's a guard written in code, not a
> prompt asking the model to behave."

(If nothing was removed, say instead: "When the model writes a number it can't support, this
is where the removed sentence would appear.")

**1:40–2:00 · The close** (About page, architecture diagram)

> "Under the hood: Kafka Streams in Java for the decisions, an XGBoost model behind gRPC with a
> circuit breaker, so the stream never waits for it, Postgres for cases, and a LangGraph agent
> that can only read. It all runs on one laptop at zero cost, and the replay of it is live on
> GitHub Pages. Link below."

End on the About page for two seconds.

## After recording

- Trim dead air in any editor; the scenario takes about a minute of real time, so cut the
  wait between 0:20 and 0:35 if it drags.
- Upload unlisted to YouTube (or to LinkedIn directly), then put the link in the README's
  links row, next to "Open the console".
