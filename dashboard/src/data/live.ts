import { ASK_FIXTURE } from '../config';
import { agentApi, api, ApiError, AskError, feedUrl } from '../lib/api';
import type { FeedTick } from '../lib/types';
import { normalizeAsk } from './ask';
import type { AgentStatus, DataSource, FeedConnection, FeedSink } from './source';

/** Case service over HTTP + WebSocket, analyst agent over HTTP under /agent. */
export function createLiveSource(): DataSource {
  return {
    mode: 'live',
    connectFeed: connectWebSocket,
    stats: (signal) => api.stats(signal),
    cases: (q, signal) => api.cases(q, signal),
    caseDetail: (caseId, signal) => api.caseDetail(caseId, signal),
    userHistory: (userId, signal) => api.userHistory(userId, 24, signal),
    neighborhood: (userId, signal) => api.neighborhood(userId, 2, signal),
    setStatus: (caseId, status) => api.setStatus(caseId, status),
    manifest: async () => null,
    openableCases: async () => null,
    recordedQuestions: async () => null,

    agentStatus: async (signal): Promise<AgentStatus> => {
      // import.meta.env.DEV repeated at each use so the build folds the branch away.
      if (import.meta.env.DEV && ASK_FIXTURE) return { state: 'up', model: 'dev fixture', provider: null, fixture: true };
      const health = await agentApi.health(signal);
      if (!health) return { state: 'down', reason: 'unreachable' };
      if (health.status !== 'UP') return { state: 'down', reason: 'no_model' };
      return { state: 'up', model: health.model ?? null, provider: health.provider ?? null, fixture: false };
    },

    ask: async (caseId, question, history) => {
      if (import.meta.env.DEV && ASK_FIXTURE) return fixtureAsk(caseId, question);
      let raw: unknown;
      try {
        raw = await agentApi.ask(caseId, question, history);
      } catch (err) {
        throw await explain404(err, caseId);
      }
      return normalizeAsk(raw, caseId, question, 'live');
    },
  };
}

/**
 * A 404 from the ask endpoint means "unknown case" (contract §2), but an agent
 * deployed before the endpoint existed answers every path with a 404 too.
 * Asking the case service settles which one it is, so the reader is never told
 * a case is gone while it is on the screen.
 */
async function explain404(err: unknown, caseId: string): Promise<unknown> {
  if (!(err instanceof AskError) || err.kind !== 'not_found') return err;
  try {
    await api.caseDetail(caseId);
  } catch {
    return err; // the case really is gone (or the case service cannot say otherwise)
  }
  return new AskError('unsupported', 404, 'The analyst in this deployment does not take questions.');
}

/**
 * Development only (see ASK_FIXTURE in config.ts): a fixture answer built from
 * the real case, after a pause that feels like a model call. The dynamic import
 * sits behind a build-time constant, so production bundles drop it entirely.
 */
async function fixtureAsk(caseId: string, question: string) {
  const { buildFixtureAnswer } = await import('./askFixture');
  let detail;
  try {
    detail = await api.caseDetail(caseId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) throw new AskError('not_found', 404, 'The case no longer exists.');
    throw new AskError('unreachable', 0, 'Cannot reach the case service.');
  }
  const [history, graph] = await Promise.all([
    api.userHistory(detail.userId, 24).catch(() => null),
    api.neighborhood(detail.userId, 2).catch(() => null),
  ]);
  await new Promise((r) => window.setTimeout(r, 1100));
  const answer = buildFixtureAnswer({ detail, history, graph, question, model: 'dev fixture (no model called)' });
  return normalizeAsk(answer, caseId, question, 'live');
}

/* ---------- the decision stream ---------- */

const BACKOFF_MS = [500, 1_000, 2_000, 4_000, 8_000, 15_000];

function isTick(v: unknown): v is FeedTick {
  return !!v && typeof v === 'object' && typeof (v as FeedTick).txnId === 'string';
}

/**
 * Plain WebSocket to /ws/feed. The server backfills the last 200 ticks on
 * connect, then batches into a JSON array about every 200 ms. Reconnects with
 * capped exponential backoff and jitter.
 */
function connectWebSocket(sink: FeedSink): FeedConnection {
  let closed = false;
  let socket: WebSocket | null = null;
  let timer: number | undefined;
  let attempt = 0;
  // Bumped on every connect so a socket that was replaced (a manual retry,
  // StrictMode's double effect) can no longer drive state or schedule retries.
  let generation = 0;

  const connect = () => {
    if (closed) return;
    const gen = ++generation;
    const current = () => gen === generation && !closed;

    sink.state('connecting', attempt, null);
    let ws: WebSocket;
    try {
      ws = new WebSocket(feedUrl());
    } catch (err) {
      schedule(err instanceof Error ? err.message : 'Could not open the decision stream.');
      return;
    }
    socket = ws;
    let first = true;

    ws.onopen = () => {
      if (!current()) return;
      attempt = 0;
      sink.state('open', 0, null);
    };

    ws.onmessage = (ev: MessageEvent) => {
      if (!current()) return;
      let payload: unknown;
      try {
        payload = JSON.parse(String(ev.data));
      } catch {
        return; // one bad frame is not worth a reconnect
      }
      // Contract says an array of ticks; tolerate a lone object defensively.
      const batch = (Array.isArray(payload) ? payload : [payload]).filter(isTick);
      const backfill = first;
      first = false;
      if (batch.length > 0) sink.batch(batch, backfill);
    };

    ws.onclose = (ev: CloseEvent) => {
      if (socket === ws) socket = null;
      if (!current()) return;
      schedule(ev.code !== 1000 && ev.reason ? ev.reason : null);
    };
  };

  const schedule = (error: string | null) => {
    const base = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
    attempt += 1;
    sink.state('closed', attempt, error);
    timer = window.setTimeout(connect, base * (0.8 + Math.random() * 0.4));
  };

  // Open on the next tick rather than now: a caller that closes straight away
  // (React StrictMode's double effect in development) then never creates a
  // socket at all, instead of tearing one down mid-handshake.
  sink.state('connecting', 0, null);
  timer = window.setTimeout(connect, 0);

  return {
    close() {
      closed = true;
      generation += 1;
      window.clearTimeout(timer);
      socket?.close(1000, 'closed');
      socket = null;
    },
    retry() {
      if (closed) return;
      window.clearTimeout(timer);
      generation += 1;
      attempt = 0;
      socket?.close(1000, 'manual reconnect');
      socket = null;
      connect();
    },
  };
}
