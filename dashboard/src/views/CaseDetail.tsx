import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { READ_ONLY } from '../config';
import { source } from '../data';
import { isNotFound } from '../lib/api';
import {
  DASH,
  fmtClockMs,
  fmtDateTime,
  fmtMoney0,
  fmtNum,
  fmtPct,
  fmtScore,
  fmtSecs,
  fmtValue,
  fmtWhen,
  parseTime,
  shortId,
  titleCase,
} from '../lib/format';
import { useManifest } from '../lib/hooks';
import { normalizeReport } from '../lib/report';
import { featureKey, featureLabel, merchantCategory } from '../lib/signals';
import {
  CASE_STATUSES,
  type CaseDetail as Detail,
  type CaseStatus,
  type DecisionDoc,
  type Neighborhood,
  type UserHistory,
} from '../lib/types';
import type { AsyncState } from '../lib/useAsync';
import { useAsync } from '../lib/useAsync';
import { AnalystReport } from '../components/AnalystReport';
import { Async, ErrorBox, Glyph, Loading, ModeTag, RuleWords, Section, StatusBadge, VerdictPill } from '../components/Bits';
import { GraphView } from '../components/GraphView';
import { ShapChart } from '../components/ShapChart';
import { SignalCard } from '../components/SignalCard';

const REPLAY = source.mode === 'replay';
/** A case this young may still be waiting for its report; older ones are not coming. */
export const REPORT_WAIT_MS = 10 * 60_000;

/**
 * The centre pane: one case, investigated. Ordered for a reader who has never
 * seen a fraud console: the verdict, why in plain words, what the analyst
 * concluded, then the model's reasoning and the raw material behind it.
 */
export function CaseDetail({
  caseId,
  state,
  isDefault,
  onAsk,
}: {
  caseId: string | null;
  state: AsyncState<Detail>;
  isDefault: boolean;
  onAsk: () => void;
}) {
  const paneRef = useRef<HTMLElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const prevRef = useRef<string | null | undefined>(undefined);

  // A new case starts at its top. On a phone, where the panes stack, bring the
  // case into view too — but not on first load, which would skip the feed.
  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = caseId;
    if (prev === caseId) return;
    bodyRef.current?.scrollTo?.(0, 0);
    if (prev && caseId && window.matchMedia?.('(max-width: 699px)').matches) {
      paneRef.current?.scrollIntoView({ block: 'start' });
    }
  }, [caseId]);

  return (
    <section className="pane pane--case" aria-label="Case investigation" ref={paneRef}>
      <header className="pane__head">
        <h2 className="label">Case investigation</h2>
        <span className="pane__meta faint">
          {caseId && isDefault ? (REPLAY ? 'featured case' : 'latest reported case') : null}
        </span>
        <button type="button" className="btn btn--small ask-open" onClick={onAsk} disabled={!caseId}>
          <Glyph name="chat" /> Ask the analyst
        </button>
      </header>
      <div className="pane__body case" ref={bodyRef}>
        {!caseId ? (
          <p className="state state--empty">
            Pick a flagged decision in the feed to investigate it. Only REVIEW and BLOCK decisions
            open cases.
          </p>
        ) : state.error && !state.data ? (
          isNotFound(state.error) ? (
            <p className="state state--empty">
              {REPLAY ? (
                <>This case was not recorded in the replay.</>
              ) : (
                <>
                  No case <span className="mono">{caseId}</span>. It may belong to a different database,
                  or the link is wrong.
                </>
              )}
            </p>
          ) : (
            <ErrorBox error={state.error} onRetry={state.reload} />
          )
        ) : !state.data ? (
          <Loading label="Loading the case…" />
        ) : (
          <Loaded detail={state.data} onUpdated={state.set} />
        )}
      </div>
    </section>
  );
}

function Loaded({ detail, onUpdated }: { detail: Detail; onUpdated: (d: Detail) => void }) {
  const d: Partial<DecisionDoc> = detail.decisionDoc ?? {};
  const userId = detail.userId ?? d.userId;
  const manifest = useManifest();
  const featured = manifest.data?.featured?.find((f) => f.caseId === detail.caseId) ?? null;

  const graph = useAsync<Neighborhood>((s) => source.neighborhood(userId, s), [userId]);
  const history = useAsync<UserHistory>((s) => source.userHistory(userId, s), [userId]);

  const signals = d.signals ?? [];
  const ringCycles = signals
    .filter((s) => s.code === 'RING_SUSPECT' && Array.isArray(s.evidence?.cycle))
    .map((s) => (s.evidence.cycle as unknown[]).map(String));
  const contributions = d.contributions ?? [];
  const score = detail.mlScore ?? d.mlScore ?? null;
  const hardRule = (d.firedRules ?? detail.firedRules ?? []).some((r) => r === 'HARD_BLOCK_MERCHANT' || r === 'AMOUNT_CAP');

  return (
    <>
      {featured ? (
        <p className="featured">
          <span className="label">Featured</span> <strong>{featured.title}</strong> {featured.blurb}
        </p>
      ) : null}

      <div className="casehead">
        <div className="casehead__top">
          <VerdictPill verdict={detail.verdict} size="lg" />
          <ModeTag mode={d.mode ?? 'FULL'} />
          <Metric label="Model score" value={fmtScore(score)} big />
          <Metric
            label="Latency"
            value={`${fmtNum(d.latencyMs, 0)} ms`}
            title="From the payment's own timestamp to the verdict"
          />
          <Metric label="Decided" value={fmtWhen(d.decidedAt ?? detail.createdAt)} title={fmtDateTime(d.decidedAt)} />
        </div>
        <dl className="casehead__facts">
          <Fact label="Account" value={<span className="mono">{userId}</span>} />
          {d.merchantId ? (
            <Fact
              label="Merchant"
              value={
                <>
                  <span className="mono">{d.merchantId}</span>
                  {merchantCategory(d.merchantCategory) ? (
                    <span className="dim"> · {merchantCategory(d.merchantCategory)}</span>
                  ) : null}
                </>
              }
            />
          ) : null}
          <Fact label="Case" value={<span className="mono" title={detail.caseId}>{shortId(detail.caseId)}</span>} />
          <Fact
            label="Transaction"
            value={<span className="mono" title={detail.txnId}>{shortId(detail.txnId ?? d.txnId)}</span>}
          />
          <Fact label="Status" value={<StatusBadge status={detail.status} />} />
        </dl>
        {!READ_ONLY ? <StatusControl detail={detail} onUpdated={onUpdated} /> : null}
      </div>

      {d.mode === 'DEGRADED' ? (
        <p className="state state--warn">
          Decided in <strong>DEGRADED</strong> mode: the ML scorer was unreachable or its circuit
          breaker was open, so the rules decided alone. There is no model score and no attribution.
        </p>
      ) : null}

      <Section label="Why it was flagged" id="why">
        {signals.length > 0 ? (
          <div className="signals">
            {signals.map((s, i) => (
              <SignalCard key={`${s.code}-${i}`} signal={s} />
            ))}
          </div>
        ) : (
          <p className="state state--empty">
            No rule fired on this payment.{' '}
            {score !== null
              ? `The model's score of ${fmtScore(score)} alone put it over the threshold.`
              : 'No signals were recorded with the decision.'}
          </p>
        )}
      </Section>

      <Section
        label="Analyst report"
        id="report"
        note="Written after the case opened, by an agent that can only call read-only tools. Every claim cites the evidence behind it."
      >
        {detail.reportDoc ? (
          <AnalystReport report={detail.reportDoc} />
        ) : (
          <NoReport detail={detail} />
        )}
      </Section>

      <Section
        label="Model attribution"
        id="shap"
        note="SHAP values: how much each feature moved the model's log-odds of fraud."
      >
        {contributions.length > 0 ? (
          <ShapChart contributions={contributions} />
        ) : (
          <p className="state state--empty">
            {d.mode === 'DEGRADED'
              ? 'No attribution: the model was not reachable for this decision.'
              : score === null
                ? hardRule
                  ? 'No attribution: a hard rule decided before the model was consulted.'
                  : 'No attribution: the model was not consulted for this decision.'
                : 'No attribution: explanations are only computed when the model scores 0.4 or more.'}
          </p>
        )}
      </Section>

      <Section
        label="Transaction network"
        id="graph"
        note={`Peer-to-peer transfers around ${userId}, two hops out, from the engine's in-memory graph.`}
      >
        <Async
          state={graph}
          empty="The engine returned no neighbourhood for this account."
          missing="The network around this account was not recorded in this replay."
        >
          {(nb) => <GraphView nb={nb} cycles={ringCycles} />}
        </Async>
      </Section>

      <Section label="Account activity" id="activity" note={REPLAY ? 'As recorded, last 24 hours.' : 'Live state from the stream engine, last 24 hours.'}>
        <Async
          state={history}
          empty="No history for this account."
          missing="This account's activity was not recorded in this replay."
        >
          {(h) => <History h={h} />}
        </Async>
      </Section>

      <Section label="Feature vector" id="features" note="Exactly what the engine sent to the model.">
        {d.features && Object.keys(d.features).length > 0 ? (
          <dl className="kv kv--grid">
            {Object.entries(d.features).map(([k, v]) => (
              <div className="kv__row" key={k}>
                <dt title={k}>{featureLabel(k)}</dt>
                <dd className="mono num">{featureValue(k, v)}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="state state--empty">No feature vector on this decision.</p>
        )}
      </Section>

      <Section label="Case timeline" id="timeline">
        <Timeline detail={detail} />
      </Section>
    </>
  );
}

function NoReport({ detail }: { detail: Detail }) {
  const age = Date.now() - parseTime(detail.createdAt);
  if (!REPLAY && age >= 0 && age < REPORT_WAIT_MS) {
    return (
      <p className="state state--pending" role="status">
        The analyst is investigating this case. Its report appears here when it finishes, usually
        within a minute; this panel checks every few seconds.
      </p>
    );
  }
  return (
    <p className="state state--empty">
      No analyst report on this case. The agent runs after a case opens and attaches a report when it
      finishes; for this one it was disabled, still queued, or failed.
    </p>
  );
}

function Metric({ label, value, title, big }: { label: string; value: string; title?: string; big?: boolean }) {
  return (
    <span className="metric" title={title}>
      <span className="label">{label}</span>
      <span className={big ? 'metric__value metric__value--big mono' : 'metric__value mono'}>{value}</span>
    </span>
  );
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="fact">
      <dt className="label">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function featureValue(key: string, v: unknown): string {
  if (v === null || v === undefined) return DASH;
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v !== 'number') return String(v);
  switch (featureKey(key)) {
    case 'sum1h':
      return fmtMoney0(v);
    case 'geoSpeedKmh':
      return `${fmtNum(v, 0)} km/h`;
    case 'secsSinceLast':
    case 'secsSinceInbound':
      return fmtSecs(v);
    case 'passThroughRatio':
      return fmtPct(v, 1);
    case 'amtZ':
      return `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}`;
    default:
      return fmtNum(v, 2);
  }
}

function StatusControl({ detail, onUpdated }: { detail: Detail; onUpdated: (d: Detail) => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = async (status: CaseStatus) => {
    if (status === detail.status) return;
    setSaving(true);
    setError(null);
    try {
      onUpdated(await source.setStatus(detail.caseId, status));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update the status.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="statuscontrol">
      <label className="field">
        <span className="label">Set status</span>
        <select
          className="select"
          value={detail.status}
          disabled={saving}
          onChange={(e) => void change(e.target.value as CaseStatus)}
        >
          {CASE_STATUSES.map((s) => (
            <option key={s} value={s}>
              {titleCase(s)}
            </option>
          ))}
        </select>
      </label>
      {saving ? <span className="dim small">Saving…</span> : null}
      {error ? (
        <span className="state state--error state--inline" role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}

function History({ h }: { h: UserHistory }) {
  const w = h.windows;
  return (
    <>
      <dl className="activity">
        <div className="activity__cell">
          <dt className="label">Usual payment</dt>
          <dd>
            {h.profile ? (
              <>
                <span className="mono">{fmtMoney0(h.profile.mean)}</span>{' '}
                <span className="dim">
                  ± <span className="mono">{fmtMoney0(h.profile.std)}</span> over{' '}
                  <span className="mono">{fmtNum(h.profile.n, 0)}</span> payments
                </span>
              </>
            ) : (
              <span className="dim">unavailable</span>
            )}
          </dd>
        </div>
        {(
          [
            ['Last minute', w?.cnt1m, w?.sum1m],
            ['Last 5 min', w?.cnt5m, w?.sum5m],
            ['Last hour', w?.cnt1h, w?.sum1h],
          ] as const
        ).map(([label, cnt, sum]) => (
          <div className="activity__cell" key={label}>
            <dt className="label">{label}</dt>
            <dd>
              {w ? (
                <>
                  <span className="mono">{fmtNum(cnt, 0)}</span>
                  <span className="dim"> payment{cnt === 1 ? '' : 's'} · </span>
                  <span className="mono">{fmtMoney0(sum)}</span>
                </>
              ) : (
                <span className="dim">unavailable</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {!h.profile && !h.windows ? (
        <p className="state state--warn">
          The stream engine&rsquo;s read API did not answer, so the live profile and window counts are
          missing.
        </p>
      ) : null}
      {h.recent?.length ? (
        <>
          <p className="label activity__h">Recent decisions for this account</p>
          <ul className="minifeed">
            {h.recent.slice(0, 10).map((r) => (
              <li key={r.txnId} className={`minifeed__row minifeed__row--${String(r.verdict).toLowerCase()}`}>
                <span className="mono dim" title={fmtClockMs(r.decidedAt)}>
                  {fmtWhen(r.decidedAt)}
                </span>
                <VerdictPill verdict={r.verdict} />
                <span className="mono num">{fmtScore(r.mlScore)}</span>
                <span className="minifeed__rules">
                  <RuleWords rules={r.firedRules} />
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="state state--empty">No decisions for this account in the last 24 hours.</p>
      )}
    </>
  );
}

function Timeline({ detail }: { detail: Detail }) {
  if (!detail.events?.length) return <p className="state state--empty">No events recorded for this case.</p>;
  return (
    <ol className="timeline">
      {[...detail.events]
        .sort((a, b) => (a.at < b.at ? 1 : -1))
        .map((ev, i) => (
          <li className="timeline__item" key={`${ev.eventType}-${ev.at}-${i}`}>
            <div className="timeline__head">
              <code className="rule">{ev.eventType}</code>
              <span className="dim mono" title={fmtDateTime(ev.at)}>
                {fmtWhen(ev.at)}
              </span>
            </div>
            <EventPayload ev={ev} />
          </li>
        ))}
    </ol>
  );
}

/**
 * Event payloads in the timeline. REPORT_ATTACHED carries the entire report,
 * so it collapses to the one line that says what happened.
 */
function EventPayload({ ev }: { ev: Detail['events'][number] }) {
  const payload = ev.payload;

  if (ev.eventType === 'REPORT_ATTACHED') {
    const r = normalizeReport(payload as Parameters<typeof normalizeReport>[0]);
    if (!r) return <p className="timeline__note dim">Report attached, but it was unreadable.</p>;
    const passed = r.verification?.passed;
    return (
      <p className="timeline__note">
        <code className="rule">{r.fraudType ?? 'no type'}</code>{' '}
        <span
          className={
            passed === true
              ? 'timeline__verify timeline__verify--pass'
              : passed === false
                ? 'timeline__verify timeline__verify--fail'
                : 'timeline__verify'
          }
        >
          {passed === true ? 'citations verified' : passed === false ? 'verification failed' : 'verification unknown'}
        </span>
        <span className="dim">
          {' · '}
          {r.findings.length} claim{r.findings.length === 1 ? '' : 's'} · {r.evidence.length} evidence
        </span>
      </p>
    );
  }

  if (ev.eventType === 'AGENT_STARTED' && (!payload || Object.keys(payload).length === 0)) {
    return <p className="timeline__note dim">The analyst agent began investigating.</p>;
  }

  if (!payload || Object.keys(payload).length === 0) return null;

  return (
    <dl className="kv kv--compact">
      {Object.entries(payload).map(([k, v]) => (
        <div className="kv__row" key={k}>
          <dt>{k.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase()}</dt>
          <dd className="mono">{fmtValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}
