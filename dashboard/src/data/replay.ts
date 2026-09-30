import { SHOWCASE_ROOT } from '../config';
import { ApiError, AskError, isNotFound } from '../lib/api';
import { sameQuestion } from '../lib/questions';
import type {
  CaseDetail,
  CaseSummary,
  FeedTick,
  Neighborhood,
  ReplayAnswers,
  ReplayFeed,
  ReplayTick,
  ShowcaseManifest,
  UserHistory,
} from '../lib/types';
import { normalizeAsk } from './ask';
import type { DataSource, FeedConnection, FeedSink } from './source';

/** The live server flushes a batch every 200 ms; the replay emits on the same beat. */
const STEP_MS = 200;
/** A recorded answer appears after its recorded latency, capped so a demo never waits long. */
const ANSWER_PAUSE_MS = { min: 500, max: 1_200 };

/**
 * Static files under <base>/showcase/ (docs/showcase-contract.md §3): a
 * recording of the real pipeline, replayed at its original timing. No backend.
 */
export function createReplaySource(root: string = SHOWCASE_ROOT): DataSource {
  const cache = new Map<string, Promise<unknown>>();

  /**
   * Every file is fetched once. A 404 stays cached (the file will not appear
   * later, and a second request would only log a second error); anything else
   * is forgotten so a retry can succeed.
   */
  function load<T>(path: string): Promise<T> {
    const hit = cache.get(path);
    if (hit) return hit as Promise<T>;
    const p = fetchJson<T>(root + path);
    cache.set(path, p);
    p.catch((err: unknown) => {
      if (!isNotFound(err)) cache.delete(path);
    });
    return p;
  }

  const manifest = () => load<ShowcaseManifest>('manifest.json');
  const casesFile = () => load<{ items?: CaseSummary[]; total?: number }>('cases.json');
  const askFile = (caseId: string) => load<ReplayAnswers>(`ask/${encodeURIComponent(caseId)}.json`);

  return {
    mode: 'replay',

    connectFeed: (sink) => play(sink, load<ReplayFeed>('feed.json'), manifest()),

    stats: async () => (await manifest()).stats,

    cases: async (q) => {
      const all = (await casesFile()).items ?? [];
      const items = q.status ? all.filter((c) => c.status === q.status) : all;
      return {
        items: items.slice(q.offset, q.offset + q.limit),
        total: items.length,
        limit: q.limit,
        offset: q.offset,
      };
    },

    caseDetail: (caseId) => load<CaseDetail>(`cases/${encodeURIComponent(caseId)}.json`),
    userHistory: (userId) => load<UserHistory>(`history/${encodeURIComponent(userId)}.json`),
    neighborhood: (userId) => load<Neighborhood>(`graph/${encodeURIComponent(userId)}.json`),

    setStatus: async () => {
      throw new ApiError(405, 'A replay is read-only.');
    },

    manifest: async () => manifest(),

    /**
     * The contract has no index of which cases/{id}.json files exist, so
     * cases.json is taken as that index (plus the featured cases). Probing each
     * flagged tick's file instead would log a 404 for every unrecorded case.
     */
    openableCases: async () => {
      const [file, m] = await Promise.all([casesFile(), manifest().catch(() => null)]);
      return new Set([
        ...(file.items ?? []).map((c) => c.caseId),
        ...(m?.featured ?? []).map((f) => f.caseId),
      ]);
    },

    agentStatus: async () => {
      const m = await manifest().catch(() => null);
      return { state: 'up', model: m?.agentModel ?? null, provider: null, fixture: false };
    },

    recordedQuestions: async (caseId) => {
      try {
        const file = await askFile(caseId);
        return (file.answers ?? [])
          .map((a) => a?.question)
          .filter((q): q is string => typeof q === 'string' && q.trim().length > 0);
      } catch (err) {
        if (isNotFound(err)) return [];
        throw err;
      }
    },

    ask: async (caseId, question) => {
      let file: ReplayAnswers;
      try {
        file = await askFile(caseId);
      } catch {
        throw new AskError('not_recorded', 0, 'No answers were recorded for this case.');
      }
      const hit = (file.answers ?? []).find(
        (a) => typeof a?.question === 'string' && sameQuestion(a.question, question),
      );
      if (!hit) throw new AskError('not_recorded', 0, 'That question was not recorded for this case.');
      const recorded = typeof hit.latencyMs === 'number' ? hit.latencyMs : 0;
      await sleep(Math.min(ANSWER_PAUSE_MS.max, Math.max(ANSWER_PAUSE_MS.min, recorded)));
      return { ...normalizeAsk(hit, caseId, question, 'replay'), mode: 'replay' };
    },
  };
}

async function fetchJson<T>(url: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: 'application/json' } });
  } catch {
    throw new ApiError(0, 'Could not load the recording.');
  }
  if (res.status === 404) throw new ApiError(404, 'Not recorded in this replay.');
  if (!res.ok) throw new ApiError(res.status, `${res.status} while loading the recording.`);
  // A dev server's SPA fallback answers a missing file with index.html and a 200.
  if ((res.headers.get('content-type') ?? '').includes('text/html')) {
    throw new ApiError(404, 'Not recorded in this replay.');
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(404, 'Not recorded in this replay.');
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/**
 * Replays feed.json at its recorded offsets, one batch per 200 ms step, and
 * loops. At the end of a pass the sink is told to reset, so the ticker starts
 * again from an empty list instead of showing the clock jump backwards.
 */
function play(
  sink: FeedSink,
  feedFile: Promise<ReplayFeed>,
  manifestFile: Promise<ShowcaseManifest>,
): FeedConnection {
  let stopped = false;
  let timer: number | undefined;

  sink.state('connecting', 0, null);

  Promise.all([feedFile, manifestFile.catch(() => null)]).then(
    ([feed, manifest]) => {
      if (stopped) return;
      const ticks: ReplayTick[] = (feed.ticks ?? [])
        .filter((t) => t && typeof t.txnId === 'string' && Number.isFinite(t.at))
        .sort((a, b) => a.at - b.at);
      if (ticks.length === 0) {
        sink.state('closed', 0, 'The recording has no decisions in it.');
        return;
      }
      const loopMs = Math.max(ticks[ticks.length - 1].at + STEP_MS, manifest?.durationMs ?? 0);

      let origin = performance.now();
      let lastStep = origin;
      let next = 0;
      const emitUntil = (at: number) => {
        const batch: FeedTick[] = [];
        while (next < ticks.length && ticks[next].at <= at) batch.push(ticks[next++]);
        if (batch.length > 0) sink.batch(batch, false);
      };

      const step = () => {
        const now = performance.now();
        // Background tabs throttle timers. Pause the recording while hidden
        // rather than dumping the missed seconds into one enormous batch.
        if (now - lastStep > 2_000) origin += now - lastStep - STEP_MS;
        lastStep = now;
        let elapsed = now - origin;
        if (elapsed >= loopMs) {
          emitUntil(loopMs);
          origin = now - (elapsed % loopMs);
          elapsed = now - origin;
          next = 0;
          sink.reset();
        }
        emitUntil(elapsed);
      };

      sink.state('open', 0, null);
      step();
      timer = window.setInterval(step, STEP_MS);
    },
    (err: unknown) => {
      if (stopped) return;
      sink.state(
        'closed',
        0,
        isNotFound(err) ? 'This deployment has no recording to replay.' : 'The recording could not be loaded.',
      );
    },
  );

  return {
    close() {
      stopped = true;
      window.clearInterval(timer);
    },
    retry() {
      /* a recording does not reconnect */
    },
  };
}
