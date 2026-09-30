/**
 * Build-time configuration. Every value here is fixed when the bundle is built
 * (Vite inlines import.meta.env), so a replay build carries no live code paths
 * it could take by accident.
 */

export type DataMode = 'live' | 'replay';

/** docs/showcase-contract.md §1: `live` (default) talks to the stack, `replay` reads /showcase/. */
export const DATA_MODE: DataMode = import.meta.env.VITE_DATA_MODE === 'replay' ? 'replay' : 'live';
export const IS_REPLAY = DATA_MODE === 'replay';

/** Hides every control that mutates state. A replay has nothing to mutate, so it is always read-only. */
export const READ_ONLY = IS_REPLAY || import.meta.env.VITE_READ_ONLY === 'true';

/** Case service. Empty means same-origin, which is how nginx and the dev proxy serve it. */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '');

/** Analyst agent. nginx and the dev proxy both route /agent/* to it with the prefix stripped. */
export const AGENT_BASE = (import.meta.env.VITE_AGENT_BASE ?? '/agent').replace(/\/+$/, '');

/** Replay files live under the app's base path, which is /fraudgraph/ on GitHub Pages. */
export const SHOWCASE_ROOT = `${import.meta.env.BASE_URL}showcase/`;

export const REPO_URL = 'https://github.com/heyush79/fraudgraph';
export const LLD_URL = `${REPO_URL}/blob/main/docs/fraudgraph-lld.md`;

/**
 * Development only: answer chat questions from a fixture instead of calling
 * POST /agent/cases/{id}/ask, so the chat panel can be worked on without the
 * agent. Switch it on with `?fixture` in the URL (before the `#`) or
 * VITE_ASK_FIXTURE=true. `import.meta.env.DEV` is false in every build, so the
 * fixture code never ships.
 */
export const ASK_FIXTURE: boolean =
  import.meta.env.DEV &&
  !IS_REPLAY &&
  (import.meta.env.VITE_ASK_FIXTURE === 'true' || hasQueryFlag('fixture'));

function hasQueryFlag(name: string): boolean {
  try {
    return new URLSearchParams(window.location.search).has(name);
  } catch {
    return false;
  }
}
