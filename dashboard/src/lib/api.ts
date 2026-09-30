import { AGENT_BASE, API_BASE } from '../config';
import type {
  AgentHealth,
  CaseDetail,
  CasePage,
  CaseStatus,
  ChatTurn,
  Neighborhood,
  Stats,
  UserHistory,
} from './types';

/**
 * HTTP clients for the live stack: the case service (same-origin by default so
 * the nginx build works unchanged; VITE_API_BASE points a dev build elsewhere)
 * and the analyst agent under /agent. Replay mode never imports this file's
 * network paths — see data/replay.ts.
 */

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

function url(path: string): string {
  return API_BASE + path;
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url(path), { signal, headers: { Accept: 'application/json' } });
  } catch (cause) {
    // Network-level failure: service down, DNS, CORS. fetch gives a useless
    // "Failed to fetch", so say something an operator can act on.
    if (signal?.aborted) throw cause;
    throw new ApiError(0, `Cannot reach the case service (${path}).`);
  }
  return parse<T>(res, path);
}

async function parse<T>(res: Response, path: string): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    const detail = body.slice(0, 200).trim();
    throw new ApiError(
      res.status,
      res.status === 404
        ? `Not found (${path}).`
        : `${res.status} ${res.statusText} from ${path}${detail ? ` — ${detail}` : ''}`,
    );
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(res.status, `${path} did not return JSON.`);
  }
}

export const api = {
  stats: (signal?: AbortSignal) => getJson<Stats>('/stats', signal),

  cases: (
    opts: { status?: CaseStatus | ''; limit: number; offset: number },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams();
    if (opts.status) q.set('status', opts.status);
    q.set('limit', String(opts.limit));
    q.set('offset', String(opts.offset));
    return getJson<CasePage>(`/cases?${q}`, signal);
  },

  caseDetail: (caseId: string, signal?: AbortSignal) =>
    getJson<CaseDetail>(`/cases/${encodeURIComponent(caseId)}`, signal),

  setStatus: async (caseId: string, status: CaseStatus): Promise<CaseDetail> => {
    const path = `/cases/${encodeURIComponent(caseId)}/status`;
    let res: Response;
    try {
      res = await fetch(url(path), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ status }),
      });
    } catch {
      throw new ApiError(0, 'Cannot reach the case service.');
    }
    return parse<CaseDetail>(res, path);
  },

  userHistory: (userId: string, hours: number, signal?: AbortSignal) =>
    getJson<UserHistory>(
      `/internal/users/${encodeURIComponent(userId)}/history?hours=${hours}`,
      signal,
    ),

  neighborhood: (userId: string, depth: number, signal?: AbortSignal) =>
    getJson<Neighborhood>(
      `/internal/graph/${encodeURIComponent(userId)}/neighborhood?depth=${depth}`,
      signal,
    ),
};

/** ws://host/ws/feed, derived from VITE_API_BASE or the page origin. */
export function feedUrl(): string {
  const base = API_BASE ? new URL(API_BASE, window.location.href) : new URL(window.location.href);
  const proto = base.protocol === 'https:' ? 'wss:' : 'ws:';
  const prefix = API_BASE ? base.pathname.replace(/\/+$/, '') : '';
  return `${proto}//${base.host}${prefix}/ws/feed`;
}

/* ---------- analyst agent (docs/showcase-contract.md §2) ---------- */

export type AskFailure =
  /** 404: the case is gone. */
  | 'not_found'
  /** 429: rate limited; `retryAfterSecs` says for how long. */
  | 'rate_limited'
  /** 503: no model configured, or the provider is down. */
  | 'offline'
  /** The request never got an HTTP answer (agent not deployed, proxy down, timeout). */
  | 'unreachable'
  /** Replay only: nobody recorded an answer to this question. */
  | 'not_recorded'
  /** 404 for a case that does exist: the deployed agent has no ask endpoint. */
  | 'unsupported'
  /** Anything else: a 5xx, or a body that is not an answer. */
  | 'failed';

export class AskError extends Error {
  readonly kind: AskFailure;
  readonly status: number;
  readonly retryAfterSecs: number | null;
  constructor(kind: AskFailure, status: number, message: string, retryAfterSecs: number | null = null) {
    super(message);
    this.name = 'AskError';
    this.kind = kind;
    this.status = status;
    this.retryAfterSecs = retryAfterSecs;
  }
}

/** A long answer is a few model calls on a free tier; past this the request is abandoned. */
const ASK_TIMEOUT_MS = 90_000;

export const agentApi = {
  health: async (signal?: AbortSignal): Promise<AgentHealth | null> => {
    try {
      const res = await fetch(`${AGENT_BASE}/health`, { signal, headers: { Accept: 'application/json' } });
      if (!res.ok) return null;
      return (await res.json()) as AgentHealth;
    } catch (err) {
      if (signal?.aborted) throw err;
      return null;
    }
  },

  /** Resolves to the raw body; data/ask.ts normalises it. Rejects with AskError. */
  ask: async (
    caseId: string,
    question: string,
    history: ChatTurn[],
    signal?: AbortSignal,
  ): Promise<unknown> => {
    const timeout = new AbortController();
    const timer = window.setTimeout(() => timeout.abort(), ASK_TIMEOUT_MS);
    const onAbort = () => timeout.abort();
    signal?.addEventListener('abort', onAbort, { once: true });
    let res: Response;
    try {
      res = await fetch(`${AGENT_BASE}/cases/${encodeURIComponent(caseId)}/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        // The server ignores anything older than six turns; do not send it.
        body: JSON.stringify({ question, history: history.slice(-6) }),
        signal: timeout.signal,
      });
    } catch {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      throw new AskError('unreachable', 0, timeout.signal.aborted ? 'The analyst took too long to answer.' : 'Cannot reach the analyst.');
    } finally {
      window.clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    }

    if (res.status === 404) throw new AskError('not_found', 404, 'The case no longer exists.');
    if (res.status === 429) {
      // The header is the contract; the body's retryAfterSeconds covers a proxy that drops it.
      const body = (await res.json().catch(() => null)) as { retryAfterSeconds?: unknown } | null;
      const fromBody = typeof body?.retryAfterSeconds === 'number' ? Math.ceil(body.retryAfterSeconds) : null;
      throw new AskError('rate_limited', 429, 'Rate limited.', retryAfter(res.headers.get('Retry-After')) ?? fromBody ?? 30);
    }
    if (res.status === 503) throw new AskError('offline', 503, 'The analyst is offline.');
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new AskError('failed', res.status, `${res.status} from the analyst${body ? ` — ${body.slice(0, 160)}` : ''}`);
    }
    try {
      return await res.json();
    } catch {
      throw new AskError('failed', res.status, 'The analyst did not return JSON.');
    }
  },
};

/** Retry-After is either seconds or an HTTP date (RFC 9110 §10.2.3). */
function retryAfter(header: string | null): number | null {
  if (!header) return null;
  const secs = Number(header.trim());
  if (Number.isFinite(secs) && secs >= 0) return Math.ceil(secs);
  const at = Date.parse(header);
  if (Number.isNaN(at)) return null;
  return Math.max(1, Math.ceil((at - Date.now()) / 1000));
}
