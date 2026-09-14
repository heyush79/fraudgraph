import type { ReactNode } from 'react';
import type { CaseStatus, Mode, Verdict } from '../lib/types';
import { titleCase } from '../lib/format';

export function VerdictPill({ verdict }: { verdict: Verdict | string }) {
  const key = String(verdict).toLowerCase();
  // Colour is never the only encoding — the word is always there too.
  return <span className={`pill pill--${key}`}>{verdict}</span>;
}

export function ModeTag({ mode }: { mode: Mode | string }) {
  const degraded = mode === 'DEGRADED';
  return (
    <span
      className={`tag ${degraded ? 'tag--degraded' : 'tag--full'}`}
      title={
        degraded
          ? 'ML scorer unavailable — this verdict came from rules only'
          : 'Model scored this transaction'
      }
    >
      {mode}
    </span>
  );
}

export function StatusBadge({ status }: { status: CaseStatus | string }) {
  return (
    <span className={`badge badge--${String(status).toLowerCase()}`}>
      {titleCase(String(status))}
    </span>
  );
}

export function Rules({ rules }: { rules: string[] | null | undefined }) {
  if (!rules || rules.length === 0) return <span className="dim">none</span>;
  return (
    <span className="rules">
      {rules.map((r) => (
        <code className="rule" key={r}>
          {r}
        </code>
      ))}
    </span>
  );
}

export function Mono({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span className="mono" title={title}>
      {children}
    </span>
  );
}

export function Panel({
  title,
  subtitle,
  aside,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel__head">
        <div>
          <h2 className="panel__title">{title}</h2>
          {subtitle ? <p className="panel__sub">{subtitle}</p> : null}
        </div>
        {aside ? <div className="panel__aside">{aside}</div> : null}
      </header>
      <div className="panel__body">{children}</div>
    </section>
  );
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <p className="state state--loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </p>
  );
}

export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="state state--error" role="alert">
      <p>{error.message}</p>
      {onRetry ? (
        <button type="button" className="btn btn--small" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="state state--empty">{children}</p>;
}

/**
 * loading / error / empty in one place, so no view forgets a state.
 * `isEmpty` is only consulted once data has arrived.
 */
export function Async<T>({
  state,
  empty,
  children,
  isEmpty,
}: {
  state: { data: T | null; error: Error | null; loading: boolean; reload: () => void };
  empty: ReactNode;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
}) {
  if (state.error && state.data === null) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (state.loading && state.data === null) return <Spinner />;
  if (state.data === null) return <Empty>{empty}</Empty>;
  if (isEmpty?.(state.data)) return <Empty>{empty}</Empty>;
  return (
    <>
      {state.error ? (
        <p className="state state--warn" role="status">
          Showing the last good response — refresh failed: {state.error.message}
        </p>
      ) : null}
      {children(state.data)}
    </>
  );
}
