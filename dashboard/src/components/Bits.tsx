import type { ReactNode } from 'react';
import { isNotFound } from '../lib/api';
import { titleCase } from '../lib/format';
import { ruleShort } from '../lib/signals';
import type { CaseStatus, Mode, Verdict } from '../lib/types';

export function VerdictPill({ verdict, size }: { verdict: Verdict | string; size?: 'lg' }) {
  const key = String(verdict).toLowerCase();
  // Colour is never the only encoding — the word is always there too.
  return <span className={`pill pill--${key}${size ? ` pill--${size}` : ''}`}>{verdict}</span>;
}

export function ModeTag({ mode }: { mode: Mode | string }) {
  const degraded = mode === 'DEGRADED';
  return (
    <span
      className={`tag ${degraded ? 'tag--degraded' : 'tag--full'}`}
      title={
        degraded
          ? 'DEGRADED: the ML scorer was unavailable, so rules alone decided'
          : 'FULL: rules and the ML model both decided'
      }
    >
      {mode}
    </span>
  );
}

export function StatusBadge({ status }: { status: CaseStatus | string }) {
  return (
    <span className={`badge badge--${String(status).toLowerCase()}`}>{titleCase(String(status))}</span>
  );
}

/** Rule codes as the engine wrote them. */
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

/** Rule codes in words, for tight spaces: "ring · velocity 1m". */
export function RuleWords({ rules }: { rules: string[] | null | undefined }) {
  if (!rules || rules.length === 0) return null;
  return <span title={rules.join(', ')}>{rules.map(ruleShort).join(' · ')}</span>;
}

/**
 * A section of the console: a mono uppercase label, an optional aside, and a
 * body. Sections are separated by hairlines, not boxed.
 */
export function Section({
  label,
  aside,
  note,
  children,
  id,
}: {
  label: string;
  aside?: ReactNode;
  note?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section className="section" aria-labelledby={id ? `${id}-label` : undefined}>
      <header className="section__head">
        <h3 className="label" id={id ? `${id}-label` : undefined}>
          {label}
        </h3>
        {aside ? <div className="section__aside">{aside}</div> : null}
      </header>
      {note ? <p className="section__note">{note}</p> : null}
      <div className="section__body">{children}</div>
    </section>
  );
}

/** A boxed panel, for full pages (the cases table) rather than the console. */
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

/** Static on purpose: the only motion in this app is the ticker. */
export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <p className="state state--loading" role="status">
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
 * loading / error / empty in one place, so no panel forgets a state.
 * `missing` is shown for a 404 (in a replay: the file was not recorded).
 * `isEmpty` is only consulted once data has arrived.
 */
export function Async<T>({
  state,
  empty,
  missing,
  isEmpty,
  children,
}: {
  state: { data: T | null; error: Error | null; loading: boolean; reload: () => void };
  empty: ReactNode;
  missing?: ReactNode;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
}) {
  if (state.error && state.data === null) {
    if (missing && isNotFound(state.error)) return <Empty>{missing}</Empty>;
    return <ErrorBox error={state.error} onRetry={state.reload} />;
  }
  if (state.loading && state.data === null) return <Loading />;
  if (state.data === null) return <Empty>{empty}</Empty>;
  if (isEmpty?.(state.data)) return <Empty>{empty}</Empty>;
  return (
    <>
      {state.error ? (
        <p className="state state--warn" role="status">
          Showing the last good response; the refresh failed: {state.error.message}
        </p>
      ) : null}
      {children(state.data)}
    </>
  );
}

/** A tiny inline glyph set. SVG, not emoji, and coloured by currentColor. */
export function Glyph({ name }: { name: 'sun' | 'moon' | 'check' | 'shield' | 'close' | 'chat' | 'arrow' }) {
  const common = {
    width: 14,
    height: 14,
    viewBox: '0 0 16 16',
    'aria-hidden': true,
    focusable: false,
    className: 'glyph',
  } as const;
  switch (name) {
    case 'sun':
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M8 1.5v1.8M8 12.7v1.8M1.5 8h1.8M12.7 8h1.8M3.4 3.4l1.3 1.3M11.3 11.3l1.3 1.3M3.4 12.6l1.3-1.3M11.3 4.7l1.3-1.3"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      );
    case 'moon':
      return (
        <svg {...common}>
          <path
            d="M13.5 9.6A5.8 5.8 0 0 1 6.4 2.5a5.8 5.8 0 1 0 7.1 7.1Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        </svg>
      );
    case 'check':
      return (
        <svg {...common}>
          <path d="m3.5 8.5 3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case 'shield':
      return (
        <svg {...common}>
          <path
            d="M8 1.8 2.8 3.6v4.1c0 3.1 2.2 5.4 5.2 6.5 3-1.1 5.2-3.4 5.2-6.5V3.6Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinejoin="round"
          />
          <path d="m5.6 8.1 1.7 1.7 3.2-3.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case 'close':
      return (
        <svg {...common}>
          <path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      );
    case 'chat':
      return (
        <svg {...common}>
          <path
            d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinejoin="round"
          />
        </svg>
      );
    case 'arrow':
      return (
        <svg {...common}>
          <path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
  }
}
