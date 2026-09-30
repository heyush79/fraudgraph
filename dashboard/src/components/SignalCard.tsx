import type { ReactNode } from 'react';
import type { Signal } from '../lib/types';
import {
  DASH,
  fmtMoney0,
  fmtNum,
  fmtPct,
  fmtSecs,
  fmtValue,
  humanKey,
  humanSecs,
  isNum,
  windowPhrase,
} from '../lib/format';
import { merchantCategory, nearestCity, ruleTitle } from '../lib/signals';

function num(e: Record<string, unknown>, k: string): number | null {
  const v = e[k];
  return isNum(v) ? v : null;
}

function str(e: Record<string, unknown>, k: string): string | null {
  const v = e[k];
  return typeof v === 'string' && v ? v : null;
}

function strArr(e: Record<string, unknown>, k: string): string[] | null {
  const v = e[k];
  return Array.isArray(v) ? v.map((x) => String(x)) : null;
}

/**
 * A signal's evidence as a sentence a person can read, per code, with the
 * rule code kept visible for anyone who wants to look it up. Unknown codes
 * fall back to a key/value table rather than disappearing, so the engine can
 * add rules without this file changing first.
 */
export function SignalCard({ signal }: { signal: Signal }) {
  const e = signal.evidence ?? {};
  const sev = isNum(signal.severity) ? Math.max(0, Math.min(1, signal.severity)) : null;

  return (
    <article className="signal">
      <header className="signal__head">
        <span className="signal__title">{ruleTitle(signal.code)}</span>
        <code className="signal__code">{signal.code}</code>
        {sev !== null ? (
          <span className="signal__sev" title={`Severity ${fmtNum(sev, 2)} of 1`}>
            <span className="signal__sevtrack" aria-hidden="true">
              <span className="signal__sevbar" style={{ width: `${sev * 100}%` }} />
            </span>
            <span className="signal__sevnum mono">{sev.toFixed(2)}</span>
          </span>
        ) : null}
      </header>
      <div className="signal__body">{body(signal.code, e)}</div>
    </article>
  );
}

function body(code: string, e: Record<string, unknown>): ReactNode {
  if (code.startsWith('VELOCITY')) return <Velocity e={e} />;
  if (code === 'GEO_IMPOSSIBLE') return <Geo e={e} />;
  if (code === 'RING_SUSPECT') return <Ring e={e} />;
  if (code === 'PASS_THROUGH') return <PassThrough e={e} />;
  if (code === 'HARD_BLOCK_MERCHANT') return <Merchant e={e} />;
  if (code === 'AMOUNT_CAP') return <AmountCap e={e} />;
  return <Generic e={e} />;
}

/** "18 payments in 60 seconds, limit 8 (2.3× over)." */
function Velocity({ e }: { e: Record<string, unknown> }) {
  const count = num(e, 'count');
  const limit = num(e, 'limit');
  const sum = num(e, 'sum');
  const over = count !== null && limit !== null && limit > 0 ? count / limit : null;
  return (
    <>
      <p className="signal__lead">
        <strong className="mono">{fmtNum(count, 0)}</strong> payments in{' '}
        <strong>{windowPhrase(num(e, 'windowSecs'))}</strong>, limit{' '}
        <span className="mono">{fmtNum(limit, 0)}</span>
        {over !== null && over >= 1.05 ? <> ({fmtNum(over, 1)}× over)</> : null}.
      </p>
      {sum !== null ? (
        <p className="signal__note">
          <span className="mono">{fmtMoney0(sum)}</span> moved inside that window.
        </p>
      ) : null}
    </>
  );
}

/** "1,358 km in 4 minutes: an implied 20,122 km/h against a ceiling of 900." */
function Geo({ e }: { e: Record<string, unknown> }) {
  const from = [num(e, 'fromLat'), num(e, 'fromLon')] as const;
  const to = [num(e, 'toLat'), num(e, 'toLon')] as const;
  const fromCity = nearestCity(from[0], from[1]);
  const toCity = nearestCity(to[0], to[1]);
  return (
    <>
      <p className="signal__lead">
        <strong className="mono">{fmtNum(num(e, 'distanceKm'), 0)} km</strong> in{' '}
        <strong>{humanSecs(num(e, 'gapSecs'))}</strong>: an implied{' '}
        <strong className="mono">{fmtNum(num(e, 'speedKmh'), 0)} km/h</strong>, against a ceiling of{' '}
        <span className="mono">{fmtNum(num(e, 'maxSpeedKmh'), 0)} km/h</span>.
      </p>
      <p className="signal__note">
        <Place city={fromCity} at={from} /> <span aria-hidden="true">→</span>
        <span className="sr-only">to</span> <Place city={toCity} at={to} />, {fmtSecs(num(e, 'gapSecs'))} apart.
      </p>
    </>
  );
}

function Place({ city, at }: { city: string | null; at: readonly (number | null)[] }) {
  const coords = at[0] === null || at[1] === null ? DASH : `${at[0].toFixed(3)}, ${at[1].toFixed(3)}`;
  return city ? (
    <span title={coords}>
      {city} <span className="mono faint">({coords})</span>
    </span>
  ) : (
    <span className="mono">{coords}</span>
  );
}

/**
 * Above this, "a cluster of N accounts" stops describing the ring. The engine's components only
 * ever merge (union-find cannot split when edges expire), so after a day of uptime most of the
 * honest contact network is one component and the number measures uptime, not the ring
 * (LLD §11). Small clusters are the informative case; the raw number stays in the evidence.
 */
const INFORMATIVE_CLUSTER = 50;

/** The cycle as a chain of account ids; the endpoints (the same account) are marked. */
function Ring({ e }: { e: Record<string, unknown> }) {
  const cycle = strArr(e, 'cycle') ?? [];
  const hops = num(e, 'cycleLength') ?? (cycle.length > 1 ? cycle.length - 1 : null);
  const rawComp = num(e, 'componentSize');
  const comp = rawComp !== null && rawComp <= INFORMATIVE_CLUSTER ? rawComp : null;
  const counterparty = str(e, 'counterpartyId');
  return (
    <>
      <p className="signal__lead">
        Money came back to where it started after <strong className="mono">{fmtNum(hops, 0)}</strong>{' '}
        hops{comp !== null ? (
          <>
            , inside a cluster of <strong className="mono">{fmtNum(comp, 0)}</strong> connected accounts
          </>
        ) : null}
        .
      </p>
      {cycle.length > 0 ? <Chain ids={cycle} /> : null}
      {counterparty ? (
        <p className="signal__note">
          This payment, to <span className="mono">{counterparty}</span>, is the hop that closed the loop.
        </p>
      ) : null}
    </>
  );
}

function Chain({ ids }: { ids: string[] }) {
  return (
    <ol className="chain" aria-label="Accounts in the cycle, in order">
      {ids.map((id, i) => (
        <li key={`${id}-${i}`} className={i === 0 || i === ids.length - 1 ? 'chain__end' : undefined}>
          <span className="mono">{id}</span>
        </li>
      ))}
    </ol>
  );
}

/**
 * docs/showcase-contract.md §5: "Forwarded 96% of ₹41,230 received from
 * u_14106 three minutes earlier; the money has now passed through 2 accounts
 * in a row."
 */
function PassThrough({ e }: { e: Record<string, unknown> }) {
  const from = str(e, 'inboundFrom');
  const to = str(e, 'counterpartyId');
  const depth = num(e, 'chainDepth');
  const inbound = num(e, 'inboundAmount');
  const outbound = num(e, 'outboundAmount');
  return (
    <>
      <p className="signal__lead">
        Forwarded <strong className="mono">{fmtPct(num(e, 'ratio'))}</strong> of{' '}
        <span className="mono">{fmtMoney0(inbound)}</span> received from{' '}
        <span className="mono">{from ?? 'another account'}</span>{' '}
        <strong>{humanSecs(num(e, 'secsSinceInbound'))}</strong> earlier
        {depth !== null ? (
          <>
            ; the money has now passed through <strong className="mono">{fmtNum(depth, 0)}</strong>{' '}
            account{depth === 1 ? '' : 's'} in a row
          </>
        ) : null}
        .
      </p>
      <p className="signal__note">
        <span className="mono">{fmtMoney0(outbound)}</span> went on to{' '}
        <span className="mono">{to ?? 'the next account'}</span>. Passing money quickly through a chain
        of accounts is called layering.
      </p>
    </>
  );
}

function Merchant({ e }: { e: Record<string, unknown> }) {
  const id = str(e, 'merchantId');
  const cat = merchantCategory(str(e, 'merchantCategory'));
  const reason = str(e, 'reason');
  return (
    <>
      <p className="signal__lead">
        Paid <span className="mono">{id ?? 'a merchant'}</span>
        {cat ? <>, a {cat} merchant</> : null}, which is on the sanctions blocklist. A hard rule
        blocks it outright, whatever the model says.
      </p>
      {reason ? <p className="signal__note">Engine&rsquo;s reason: {reason}.</p> : null}
    </>
  );
}

function AmountCap({ e }: { e: Record<string, unknown> }) {
  return (
    <p className="signal__lead">
      <strong className="mono">{fmtMoney0(num(e, 'amount'))}</strong> is above the{' '}
      <span className="mono">{fmtMoney0(num(e, 'capInr'))}</span> per-payment cap. A hard rule blocks
      it outright, whatever the model says.
    </p>
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
