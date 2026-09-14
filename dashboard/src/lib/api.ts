import type {
  CaseDetail,
  CasePage,
  CaseStatus,
  Neighborhood,
  Stats,
  UserHistory,
} from './types';

/**
 * Same-origin by default so the nginx production build works unchanged; set
 * VITE_API_BASE to point a dev build at a case-service elsewhere.
 */
const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '');

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function url(path: string): string {
  return BASE + path;
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
  const base = BASE ? new URL(BASE, window.location.href) : new URL(window.location.href);
  const proto = base.protocol === 'https:' ? 'wss:' : 'ws:';
  const prefix = BASE ? base.pathname.replace(/\/+$/, '') : '';
  return `${proto}//${base.host}${prefix}/ws/feed`;
}
