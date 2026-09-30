import { useCallback, useEffect, useState } from 'react';

export interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  /** Re-runs the fetch; also usable as a manual retry from an error state. */
  reload: () => void;
  /** Replace the data locally (e.g. after a PATCH returns the new entity). */
  set: (value: T) => void;
}

interface Slot<T> {
  key: string;
  data: T | null;
  error: Error | null;
  loading: boolean;
}

/**
 * Every panel in this app is "fetch one thing, show loading / error / empty".
 * This is that, with abort-on-change and an optional polling interval.
 *
 * Changing `deps` blanks the data at once (the next case's panel must never
 * show the previous case's numbers, even for one render); a poll or a reload
 * refreshes in place and keeps the last good data on screen if it fails.
 */
export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  pollMs?: number,
): AsyncState<T> {
  const key = JSON.stringify(deps);
  const [slot, setSlot] = useState<Slot<T>>(() => ({ key, data: null, error: null, loading: true }));
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const ac = new AbortController();
    let live = true;

    const run = (first: boolean) => {
      if (first) {
        setSlot((s) =>
          s.key === key ? { ...s, loading: true } : { key, data: null, error: null, loading: true },
        );
      }
      fn(ac.signal).then(
        (data) => {
          if (live) setSlot({ key, data, error: null, loading: false });
        },
        (err: unknown) => {
          if (!live || ac.signal.aborted) return;
          const error = err instanceof Error ? err : new Error(String(err));
          setSlot((s) => ({ key, data: s.key === key ? s.data : null, error, loading: false }));
        },
      );
    };

    run(true);
    const timer = pollMs ? window.setInterval(() => run(false), pollMs) : undefined;
    return () => {
      live = false;
      ac.abort();
      if (timer) window.clearInterval(timer);
    };
    // `fn` is a fresh closure every render; `key` is what identifies the fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, nonce, pollMs]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const set = useCallback(
    (data: T) => setSlot((s) => ({ key: s.key, data, error: null, loading: false })),
    [],
  );

  const current: Slot<T> = slot.key === key ? slot : { key, data: null, error: null, loading: true };
  return { data: current.data, error: current.error, loading: current.loading, reload, set };
}
