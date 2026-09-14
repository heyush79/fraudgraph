import type { ReactNode } from 'react';
import type { Signal } from '../lib/types';
import { DASH, fmtSecs, fmtMoney, fmtNum, humanKey, fmtValue, isNum } from '../lib/format';

function num(e: Record<string, unknown>, k: string): number | null {
  const v = e[k];
  return isNum(v) ? v : null;
}

function strArr(e: Record<string, unknown>, k: string): string[] | null {
  const v = e[k];
  return Array.isArray(v) ? v.map((x) => String(x)) : null;
}

/**
 * Renders a signal's evidence as a sentence a human can read, per code.
 * Unknown codes fall back to a key/value table rather than disappearing —
 * the engine can add rules without this file being updated first.
 */
export function SignalCard({ signal }: { signal: Signal }) {
  const e = signal.evidence ?? {};
  const sev = isNum(signal.severity) ? Math.max(0, Math.min(1, signal.severity)) : 0;

  return (
    <article className="signal">
      <header className="signal__head">
        <code className="signal__code">{signal.code}</code>
        <span className="signal__sev" title={`severity ${fmtNum(signal.severity, 2)}`}>
          <span className="signal__sevbar" style={{ width: `${sev * 100}%` }} />
          <span className="signal__sevnum mono">{fmtNum(signal.severity, 2)}</span>
        </span>
      </header>
      <div className="signal__body">{body(signal.code, e)}</div>
    </article>
  );
}

function body(code: string, e: Record<string, unknown>): ReactNode {
  if (code.startsWith('VELOCITY')) return <Velocity e={e} />;
  if (code === 'GEO_IMPOSSIBLE') return <Geo e={e} />;
  if (code === 'RING_SUSPECT') return <Ring e={e} />;
  return <Generic e={e} />;
}

function Velocity({ e }: { e: Record<string, unknown> }) {
  const count = num(e, 'count');
  const limit = num(e, 'limit');
  const win = num(e, 'windowSecs');
  const sum = num(e, 'sum');
  const over = count !== null && limit !== null && limit > 0 ? count / limit : null;
  return (
    <>
      <p className="signal__lead">
        <strong className="mono">{fmtNum(count, 0)}</strong> transactions in{' '}
        <strong>{fmtSecs(win)}</strong> — the limit is{' '}
        <strong className="mono">{fmtNum(limit, 0)}</strong>
        {over !== null ? <> ({fmtNum(over, 1)}× over)</> : null}.
      </p>
      <p className="signal__note">
        {fmtMoney(sum)} moved inside that window.
      </p>
    </>
  );
}

function Geo({ e }: { e: Record<string, unknown> }) {
  const dist = num(e, 'distanceKm');
  const gap = num(e, 'gapSecs');
  const speed = num(e, 'speedKmh');
  const max = num(e, 'maxSpeedKmh');
  const from = [num(e, 'fromLat'), num(e, 'fromLon')] as const;
  const to = [num(e, 'toLat'), num(e, 'toLon')] as const;
  return (
    <>
      <p className="signal__lead">
        <strong className="mono">{fmtNum(dist, 0)} km</strong> apart,{' '}
        <strong>{fmtSecs(gap)}</strong> later — an implied{' '}
        <strong className="mono">{fmtNum(speed, 0)} km/h</strong>, against a ceiling of{' '}
        <span className="mono">{fmtNum(max, 0)} km/h</span>.
      </p>
      <p className="signal__note">
        from <span className="mono">{coord(from)}</span> to <span className="mono">{coord(to)}</span>
      </p>
    </>
  );
}

function coord([lat, lon]: readonly (number | null)[]): string {
  if (lat === null || lon === null) return DASH;
  return `${lat.toFixed(3)}, ${lon.toFixed(3)}`;
}

function Ring({ e }: { e: Record<string, unknown> }) {
  const cycle = strArr(e, 'cycle') ?? [];
  const len = num(e, 'cycleLength');
  const comp = num(e, 'componentSize');
  const outDeg = num(e, 'outDegree');
  const counterparty = e['counterpartyId'];
  return (
    <>
      <p className="signal__lead">
        Money returns to its origin after{' '}
        <strong className="mono">{fmtNum(len ?? (cycle.length ? cycle.length - 1 : null), 0)}</strong>{' '}
        hops, inside a connected component of{' '}
        <strong className="mono">{fmtNum(comp, 0)}</strong> accounts.
      </p>
      {cycle.length > 0 ? (
        <ol className="cycle">
          {cycle.map((id, i) => (
            <li key={`${id}-${i}`} className={i === 0 || i === cycle.length - 1 ? 'cycle__end' : ''}>
              <span className="mono">{id}</span>
            </li>
          ))}
        </ol>
      ) : null}
      <p className="signal__note">
        out-degree <span className="mono">{fmtNum(outDeg, 0)}</span>
        {typeof counterparty === 'string' ? (
          <> · this hop went to <span className="mono">{counterparty}</span></>
        ) : null}
      </p>
    </>
  );
}

function Generic({ e }: { e: Record<string, unknown> }) {
  const entries = Object.entries(e ?? {});
  if (entries.length === 0) return <p className="signal__note">No evidence attached.</p>;
  return (
    <dl className="kv kv--compact">
      {entries.map(([k, v]) => (
        <div className="kv__row" key={k}>
          <dt>{humanKey(k)}</dt>
          <dd className="mono">{fmtValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}
