import { useEffect, useMemo, useState } from 'react';
import { source } from '../data';
import type { AgentStatus } from '../data';
import { useFlagged } from './feedStore';
import { parseTime } from './format';
import { CASE_KINDS, isCaseKind, jumpLabel, kindsOf, type CaseKind } from './signals';
import type { CaseSummary, ShowcaseManifest } from './types';
import { useAsync, type AsyncState } from './useAsync';

/** Date.now(), refreshed every `ms` while `on` — for countdowns and "12s ago". */
export function useNow(ms: number, on = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return undefined;
    setNow(Date.now());
    const t = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(t);
  }, [ms, on]);
  return now;
}

/** The replay manifest; null in live mode. Fetched once and cached by the source. */
export function useManifest(): AsyncState<ShowcaseManifest | null> {
  return useAsync((s) => source.manifest(s), ['manifest']);
}

/**
 * Which case ids open a detail view. `null`: all of them (live). `undefined`:
 * not known yet, so nothing is linked until it is.
 */
export function useOpenableCases(): ReadonlySet<string> | null | undefined {
  const st = useAsync((s) => source.openableCases(s), ['openable']);
  if (st.data) return st.data;
  return st.loading || st.error ? undefined : null;
}

/** Live: GET /agent/health, re-checked every minute. Replay: always available. */
export function useAgentStatus(): AsyncState<AgentStatus> {
  return useAsync((s) => source.agentStatus(s), ['agent'], source.mode === 'live' ? 60_000 : undefined);
}

export interface JumpTarget {
  caseId: string;
  kind: CaseKind | null;
  label: string;
  /** From the manifest (replay); null in live mode. */
  title: string | null;
  blurb: string | null;
}

/**
 * The lists both the intro strip and the console's default selection are
 * derived from, fetched once per page (two components ask for them).
 */
const listCache = new Map<string, Promise<CaseSummary[]>>();
function caseList(key: string, load: () => Promise<CaseSummary[]>): Promise<CaseSummary[]> {
  let p = listCache.get(key);
  if (!p) {
    p = load();
    listCache.set(key, p);
    p.catch(() => listCache.delete(key));
  }
  return p;
}

function useCaseLists() {
  const replay = source.mode === 'replay';
  const manifest = useManifest();
  // Replay reads cases.json only to word the POLICY button by the rule that fired.
  const recent = useAsync(
    () => caseList('recent', () => source.cases({ limit: replay ? 1_000 : 200, offset: 0 }).then((p) => p.items ?? [])),
    ['jump-recent'],
  );
  const reported = useAsync(
    () =>
      replay
        ? Promise.resolve([] as CaseSummary[])
        : caseList('reported', () =>
            source.cases({ status: 'REPORTED', limit: 100, offset: 0 }).then((p) => p.items ?? []),
          ),
    ['jump-reported'],
  );
  return { replay, manifest, recent, reported };
}

/**
 * The case the console shows at #/ before anything is picked. Replay: the
 * first featured case. Live: the most recent case with an analyst report,
 * else the most recent case. Does not follow the feed, so it never moves
 * under the reader.
 */
export function useDefaultCaseId(): { caseId: string | null; ready: boolean } {
  const { replay, manifest, recent, reported } = useCaseLists();
  if (replay) {
    const first = manifest.data?.featured?.find((f) => f && typeof f.caseId === 'string');
    return { caseId: first?.caseId ?? null, ready: !manifest.loading };
  }
  return {
    caseId: reported.data?.[0]?.caseId ?? recent.data?.[0]?.caseId ?? null,
    ready: !recent.loading && !reported.loading,
  };
}

/**
 * "Show me a laundering ring" and friends. Replay: the manifest's featured
 * cases, in its order. Live: the most recent case of each kind, from the case
 * list at load plus whatever the feed has flagged since.
 */
export function useJumpTargets(): { targets: JumpTarget[]; ready: boolean } {
  const { replay, manifest, recent, reported } = useCaseLists();
  const flagged = useFlagged();

  const featured = manifest.data?.featured;
  const recentItems = recent.data;
  const reportedItems = reported.data;
  const liveFlagged = replay ? null : flagged;
  const ready = replay ? !manifest.loading : !recent.loading && !reported.loading;

  const targets = useMemo<JumpTarget[]>(() => {
    if (replay) {
      const rulesOf = new Map((recentItems ?? []).map((c) => [c.caseId, c.firedRules] as const));
      return (featured ?? [])
        .filter((f) => f && typeof f.caseId === 'string')
        .map((f) => {
          const kind = isCaseKind(f.pattern) ? f.pattern : null;
          return {
            caseId: f.caseId,
            kind,
            label: kind ? jumpLabel(kind, rulesOf.get(f.caseId)) : `Show me: ${f.title}`,
            title: f.title || null,
            blurb: f.blurb || null,
          };
        });
    }

    // Most recent per kind, except that a closed ring outranks a pass-through
    // chain for the ring button: it is the pattern the button promises.
    const rank = (k: CaseKind, rules: readonly string[]) => (k === 'RING' && rules.includes('RING_SUSPECT') ? 1 : 0);
    const best = new Map<CaseKind, { caseId: string; at: number; rules: string[] }>();
    const consider = (caseId: string | null, rules: string[] | null | undefined, at: number) => {
      if (!caseId) return;
      const r = rules ?? [];
      for (const k of kindsOf(r)) {
        const cur = best.get(k);
        const better =
          !cur || rank(k, r) > rank(k, cur.rules) || (rank(k, r) === rank(k, cur.rules) && at > cur.at);
        if (better) best.set(k, { caseId, at, rules: r });
      }
    };
    for (const c of [...(recentItems ?? []), ...(reportedItems ?? [])]) {
      consider(c.caseId, c.firedRules, parseTime(c.createdAt) || 0);
    }
    for (const t of liveFlagged ?? []) consider(t.caseId, t.firedRules, parseTime(t.decidedAt) || 0);

    return CASE_KINDS.flatMap((k) => {
      const hit = best.get(k);
      return hit ? [{ caseId: hit.caseId, kind: k, label: jumpLabel(k, hit.rules), title: null, blurb: null }] : [];
    });
  }, [replay, featured, recentItems, reportedItems, liveFlagged]);

  return { targets, ready };
}
