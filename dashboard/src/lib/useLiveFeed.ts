import { useCallback, useEffect, useRef, useState } from 'react';
import { feedUrl } from './api';
import type { FeedTick } from './types';

export type ConnState = 'connecting' | 'open' | 'closed';

export interface LiveFeed {
  ticks: FeedTick[];
  state: ConnState;
  /** Consecutive failed connects; 0 once a socket opens. */
  attempt: number;
  lastError: string | null;
  received: number;
  clear: () => void;
  reconnectNow: () => void;
}

const BACKOFF_MS = [500, 1_000, 2_000, 4_000, 8_000, 15_000];

function isTick(v: unknown): v is FeedTick {
  return !!v && typeof v === 'object' && typeof (v as FeedTick).txnId === 'string';
}

/**
 * Plain WebSocket to /ws/feed. The server batches ticks into a JSON array about
 * every 200ms, so the buffer is updated once per batch rather than per tick.
 * Reconnects with capped exponential backoff + jitter.
 */
export function useLiveFeed(cap = 200): LiveFeed {
  const [ticks, setTicks] = useState<FeedTick[]>([]);
  const [state, setState] = useState<ConnState>('connecting');
  const [attempt, setAttempt] = useState(0);
  const [lastError, setLastError] = useState<string | null>(null);
  const [received, setReceived] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | undefined>(undefined);
  const attemptRef = useRef(0);
  const closedByUs = useRef(false);
  // Bumped on every connect attempt so a socket that is torn down (unmount,
  // StrictMode's double-invoke, a manual reconnect) can no longer drive state
  // or schedule a retry after a newer socket has taken over.
  const genRef = useRef(0);

  const connect = useCallback(() => {
    if (closedByUs.current) return;
    const gen = ++genRef.current;
    const current = () => gen === genRef.current && !closedByUs.current;

    setState('connecting');
    let ws: WebSocket;
    try {
      ws = new WebSocket(feedUrl());
    } catch (err) {
      setLastError(err instanceof Error ? err.message : 'WebSocket construction failed');
      schedule();
      return;
    }
    socketRef.current = ws;

    ws.onopen = () => {
      if (!current()) return;
      attemptRef.current = 0;
      setAttempt(0);
      setLastError(null);
      setState('open');
    };

    ws.onmessage = (ev: MessageEvent<string>) => {
      if (!current()) return;
      let payload: unknown;
      try {
        payload = JSON.parse(ev.data);
      } catch {
        setLastError('Dropped a frame that was not JSON.');
        return;
      }
      // Contract says an array of ticks; tolerate a lone object defensively.
      const batch = (Array.isArray(payload) ? payload : [payload]).filter(isTick);
      if (batch.length === 0) return;
      // The batch arrives chronologically; the ticker is newest-first. Reverse
      // outside the updater — updaters must stay pure (StrictMode calls twice).
      const newestFirst = batch.reverse();
      setReceived((n) => n + newestFirst.length);
      setTicks((prev) => [...newestFirst, ...prev].slice(0, cap));
    };

    ws.onerror = () => {
      if (current()) setLastError('WebSocket error.');
    };

    ws.onclose = (ev: CloseEvent) => {
      if (socketRef.current === ws) socketRef.current = null;
      if (!current()) return;
      setState('closed');
      if (ev.code !== 1000 && ev.reason) setLastError(ev.reason);
      schedule();
    };

    function schedule() {
      const i = Math.min(attemptRef.current, BACKOFF_MS.length - 1);
      const base = BACKOFF_MS[i];
      const delay = base * (0.8 + Math.random() * 0.4); // jitter, avoid thundering herd
      attemptRef.current += 1;
      setAttempt(attemptRef.current);
      timerRef.current = window.setTimeout(connect, delay);
    }
  }, [cap]);

  useEffect(() => {
    closedByUs.current = false;
    connect();
    return () => {
      closedByUs.current = true;
      genRef.current += 1;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      socketRef.current?.close(1000, 'unmount');
      socketRef.current = null;
    };
  }, [connect]);

  const reconnectNow = useCallback(() => {
    if (timerRef.current) window.clearTimeout(timerRef.current);
    genRef.current += 1; // orphan the old socket's handlers
    attemptRef.current = 0;
    setAttempt(0);
    socketRef.current?.close(1000, 'manual reconnect');
    socketRef.current = null;
    connect();
  }, [connect]);

  const clear = useCallback(() => setTicks([]), []);

  return { ticks, state, attempt, lastError, received, clear, reconnectNow };
}
