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

/**
 * Every view in this app is "fetch one thing, show loading / error / empty".
 * This is that, with abort-on-unmount and an optional polling interval.
 */
export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
  pollMs?: number,
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const ac = new AbortController();
    let live = true;

    // Changing the key blanks the view; a poll refreshes it in place.
    const run = (first: boolean) => {
      if (first) setLoading(true);
      fn(ac.signal)
        .then((value) => {
          if (!live) return;
          setData(value);
          setError(null);
          setLoading(false);
        })
        .catch((err: unknown) => {
          if (!live || ac.signal.aborted) return;
          setError(err instanceof Error ? err : new Error(String(err)));
          setLoading(false);
        });
    };

    run(true);
    const timer = pollMs ? window.setInterval(() => run(false), pollMs) : undefined;
    return () => {
      live = false;
      ac.abort();
      if (timer) window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, pollMs]);

  return { data, error, loading, reload, set: setData };
}
