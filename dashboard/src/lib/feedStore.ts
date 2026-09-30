import { useSyncExternalStore } from 'react';
import type { DataSource, FeedState } from '../data';
import type { FeedConnection } from '../data/source';
import { isNum, parseTime } from './format';
import type { FeedTick, Verdict } from './types';

/**
 * The decision stream as two snapshots, so each reader re-renders only as
 * often as it needs to: the ticker changes with every batch (~5 Hz), the
 * header's numbers once a second. A module-level store with
 * useSyncExternalStore rather than a state library: the whole API is below.
 */

/** Rows kept per list. The flagged list is separate so it holds 200 flagged decisions, not the flagged 2% of 200. */
const CAP = 200;
/** Throughput is measured over the last 10 s: long enough to be steady, short enough to move. */
const RATE_WINDOW_MS = 10_000;
/** Latency percentiles over the last 30 s: ~1,500 samples at 50/s, enough for a stable p99. */
const LATENCY_WINDOW_MS = 30_000;
/** Bound on memory at benchmark rates (2,000/s would otherwise keep 60,000 samples). */
const SAMPLE_CAP = 20_000;
/** txnIds remembered for de-duplication across reconnects (each one re-sends a 200-tick backfill). */
const SEEN_CAP = 5_000;
/** A backfill older than this describes a system that was idle, not current throughput. */
const STALE_BACKFILL_MS = 15_000;

export interface TickRow extends FeedTick {
  /** React key. A replay repeats every txnId after each loop, so the pass number is part of it. */
  key: string;
  /** Rows slide in (and flagged rows flash) only when they arrive live, never from a backfill. */
  animate: boolean;
  /** performance.now() on arrival: a row that mounts later (a filter switch) must not animate. */
  arrivedAt: number;
}

export interface Ticker {
  /** Newest first. */
  all: readonly TickRow[];
  /** Newest first, REVIEW and BLOCK only. */
  flagged: readonly TickRow[];
  /** Bumped when a replay loops. */
  epoch: number;
  received: number;
}

export interface Pulse {
  conn: FeedState;
  attempt: number;
  error: string | null;
  /** Decisions per second; null until anything has arrived. */
  tps: number | null;
  p50: number | null;
  p99: number | null;
  samples: number;
  /** Every decision seen since the page opened, by verdict. */
  counts: Readonly<Record<Verdict, number>>;
}

interface Sample {
  /** performance.now() at which the decision would have arrived had it been sent alone. */
  t: number;
  ms: number;
}

class FeedStore {
  private ticker: Ticker = { all: [], flagged: [], epoch: 0, received: 0 };
  private pulse: Pulse = {
    conn: 'connecting',
    attempt: 0,
    error: null,
    tps: null,
    p50: null,
    p99: null,
    samples: 0,
    counts: { ALLOW: 0, REVIEW: 0, BLOCK: 0 },
  };
  private counts: Record<Verdict, number> = { ALLOW: 0, REVIEW: 0, BLOCK: 0 };
  private samples: Sample[] = [];
  private seen = new Set<string>();
  private seenOrder: string[] = [];
  private everSampled = false;
  private lastRecompute = Number.NEGATIVE_INFINITY;
  private conn: FeedConnection | null = null;
  private generation = 0;
  private timer: number | undefined;
  private tickerSubs = new Set<() => void>();
  private pulseSubs = new Set<() => void>();

  /** Connects to the source; returns the disconnect. Safe under StrictMode's double effect. */
  start(source: DataSource): () => void {
    this.conn?.close();
    // A generation, not the connection object: a source may report its first
    // state synchronously, before connectFeed has even returned.
    const gen = ++this.generation;
    const current = () => this.generation === gen;
    const conn = source.connectFeed({
      batch: (ticks, backfill) => {
        if (current()) this.onBatch(ticks, backfill);
      },
      state: (state, attempt, error) => {
        if (current()) this.setPulse({ ...this.pulse, conn: state, attempt, error });
      },
      reset: () => {
        if (current()) this.onReset();
      },
    });
    this.conn = conn;
    window.clearInterval(this.timer);
    // Once a second keeps the numbers readable and lets them decay if the stream stops.
    this.timer = window.setInterval(() => {
      if (performance.now() - this.lastRecompute >= 900) this.recompute();
    }, 1_000);
    return () => {
      if (!current()) return;
      this.generation += 1;
      conn.close();
      this.conn = null;
      window.clearInterval(this.timer);
    };
  }

  retry(): void {
    this.conn?.retry();
  }

  subscribeTicker = (cb: () => void) => {
    this.tickerSubs.add(cb);
    return () => {
      this.tickerSubs.delete(cb);
    };
  };

  getTicker = (): Ticker => this.ticker;

  subscribePulse = (cb: () => void) => {
    this.pulseSubs.add(cb);
    return () => {
      this.pulseSubs.delete(cb);
    };
  };

  getPulse = (): Pulse => this.pulse;

  private onBatch(batch: FeedTick[], backfill: boolean): void {
    const now = performance.now();
    const times = batch.map((t) => parseTime(t.decidedAt));
    const newest = times.reduce((m, t) => (Number.isFinite(t) && t > m ? t : m), Number.NEGATIVE_INFINITY);
    // Only differences between decidedAt values are used, never the server's
    // clock against this one, except to spot a backfill from a system that has
    // been idle — that one must not count as current throughput.
    const stale = backfill && Number.isFinite(newest) && Date.now() - newest > STALE_BACKFILL_MS;

    const fresh: TickRow[] = [];
    batch.forEach((t, i) => {
      if (this.seen.has(t.txnId)) return; // a reconnect re-sends its 200-tick backfill
      this.remember(t.txnId);
      if (t.verdict in this.counts) this.counts[t.verdict] += 1;
      if (!stale && isNum(t.latencyMs)) {
        // Spread a batch over the time its decisions actually span, so a
        // 200-tick backfill counts as the ~4 s it covers rather than one instant.
        const back = Number.isFinite(times[i]) && Number.isFinite(newest) ? newest - times[i] : 0;
        this.samples.push({ t: now - Math.min(Math.max(back, 0), LATENCY_WINDOW_MS), ms: t.latencyMs });
        this.everSampled = true;
      }
      fresh.push({ ...t, key: `${this.ticker.epoch}:${t.txnId}`, animate: !backfill, arrivedAt: now });
    });
    if (this.samples.length > SAMPLE_CAP) this.samples.splice(0, this.samples.length - SAMPLE_CAP);
    // Leading edge: the header shows numbers with the first batch, not a second later.
    if (now - this.lastRecompute >= 1_000) this.recompute();
    if (fresh.length === 0) return;

    fresh.reverse(); // batches arrive oldest first; the ticker is newest first
    const flagged = fresh.filter((r) => r.verdict !== 'ALLOW');
    this.ticker = {
      ...this.ticker,
      all: fresh.concat(this.ticker.all).slice(0, CAP),
      flagged: flagged.length > 0 ? flagged.concat(this.ticker.flagged).slice(0, CAP) : this.ticker.flagged,
      received: this.ticker.received + fresh.length,
    };
    this.tickerSubs.forEach((cb) => cb());
  }

  /** A replay looped. Clear the lists; keep counts and samples, which describe the session. */
  private onReset(): void {
    this.seen.clear();
    this.seenOrder = [];
    this.ticker = { ...this.ticker, all: [], flagged: [], epoch: this.ticker.epoch + 1 };
    this.tickerSubs.forEach((cb) => cb());
  }

  private remember(txnId: string): void {
    this.seen.add(txnId);
    this.seenOrder.push(txnId);
    if (this.seenOrder.length > SEEN_CAP) {
      for (const old of this.seenOrder.splice(0, this.seenOrder.length - SEEN_CAP)) this.seen.delete(old);
    }
  }

  private recompute(): void {
    const now = performance.now();
    this.lastRecompute = now;
    this.samples = this.samples.filter((s) => now - s.t <= LATENCY_WINDOW_MS);

    let inRate = 0;
    let oldest = now;
    for (const s of this.samples) {
      if (now - s.t <= RATE_WINDOW_MS) {
        inRate += 1;
        if (s.t < oldest) oldest = s.t;
      }
    }
    // Until 10 s of data exist, divide by the time actually covered (at least 1 s).
    const span = Math.min(RATE_WINDOW_MS, Math.max(1_000, now - oldest));
    const tps = inRate > 0 ? inRate / (span / 1_000) : this.everSampled ? 0 : null;

    const sorted = this.samples.map((s) => s.ms).sort((a, b) => a - b);
    const pct = (p: number) => (sorted.length ? sorted[Math.max(0, Math.ceil(p * sorted.length) - 1)] : null);

    const next: Pulse = {
      ...this.pulse,
      tps,
      p50: pct(0.5),
      p99: pct(0.99),
      samples: sorted.length,
      counts: { ...this.counts },
    };
    const p = this.pulse;
    const changed =
      next.tps !== p.tps ||
      next.p50 !== p.p50 ||
      next.p99 !== p.p99 ||
      next.counts.ALLOW !== p.counts.ALLOW ||
      next.counts.REVIEW !== p.counts.REVIEW ||
      next.counts.BLOCK !== p.counts.BLOCK;
    if (changed) this.setPulse(next);
  }

  private setPulse(next: Pulse): void {
    this.pulse = next;
    this.pulseSubs.forEach((cb) => cb());
  }
}

export const feedStore = new FeedStore();

export function useTicker(): Ticker {
  return useSyncExternalStore(feedStore.subscribeTicker, feedStore.getTicker);
}

export function usePulse(): Pulse {
  return useSyncExternalStore(feedStore.subscribePulse, feedStore.getPulse);
}

/** Only the flagged list: changes when a REVIEW or BLOCK arrives, not with every batch. */
export function useFlagged(): readonly TickRow[] {
  return useSyncExternalStore(feedStore.subscribeTicker, () => feedStore.getTicker().flagged);
}
