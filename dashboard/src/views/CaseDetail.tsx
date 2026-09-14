import { useState } from 'react';
import type { ReactNode } from 'react';
import { api, ApiError } from '../lib/api';
import { useAsync } from '../lib/useAsync';
import { href } from '../lib/useHashRoute';
import {
  CASE_STATUSES,
  type CaseDetail as Detail,
  type CaseStatus,
  type Neighborhood,
  type UserHistory,
} from '../lib/types';
import {
  DASH,
  fmtAgo,
  fmtDateTime,
  fmtMoney,
  fmtNum,
  fmtScore,
  fmtValue,
  humanKey,
  titleCase,
} from '../lib/format';
import { Async, ErrorBox, ModeTag, Panel, Rules, Spinner, StatusBadge, VerdictPill } from '../components/Bits';
import { SignalCard } from '../components/SignalCard';
import { ShapChart } from '../components/ShapChart';
import { GraphView } from '../components/GraphView';
import { AnalystReport } from '../components/AnalystReport';
import { normalizeReport } from '../lib/report';

export function CaseDetail({ caseId }: { caseId: string }) {
  const state = useAsync<Detail>((s) => api.caseDetail(caseId, s), [caseId]);

  return (
    <div className="detail">
      <a className="back" href={href('/cases')}>
        ← All cases
      </a>

      {state.error && !state.data ? (
        <Panel title="Case">
          {state.error instanceof ApiError && state.error.status === 404 ? (
            <p className="state state--empty">
              No case <span className="mono">{caseId}</span>. It may have been opened against a
              different database, or the id is wrong.
            </p>
          ) : (
            <ErrorBox error={state.error} onRetry={state.reload} />
          )}
        </Panel>
      ) : null}

      {!state.data && state.loading ? (
        <Panel title="Case">
          <Spinner />
        </Panel>
      ) : null}

      {state.data ? <Loaded detail={state.data} onUpdated={state.set} /> : null}
    </div>
  );
}

function Loaded({ detail, onUpdated }: { detail: Detail; onUpdated: (d: Detail) => void }) {
  const d = detail.decisionDoc;
  const userId = detail.userId ?? d?.userId;

  const graph = useAsync<Neighborhood>((s) => api.neighborhood(userId, 2, s), [userId]);
  const history = useAsync<UserHistory>((s) => api.userHistory(userId, 24, s), [userId]);

  return (
    <>
      <section className="verdictcard">
        <div className="verdictcard__main">
          <div className="verdictcard__verdict">
            <VerdictPill verdict={detail.verdict} />
            <ModeTag mode={d?.mode ?? 'FULL'} />
          </div>
          <dl className="verdictcard__facts">
            <Fact label="Model score" value={<span className="mono big">{fmtScore(detail.mlScore ?? d?.mlScore)}</span>} />
            <Fact label="Decision latency" value={<span className="mono">{fmtNum(d?.latencyMs, 0)} ms</span>} />
            <Fact label="Decided" value={<span title={fmtDateTime(d?.decidedAt)}>{fmtAgo(d?.decidedAt)}</span>} />
            <Fact label="Opened" value={<span title={fmtDateTime(detail.createdAt)}>{fmtAgo(detail.createdAt)}</span>} />
          </dl>
          <dl className="verdictcard__ids">
            <Fact label="User" value={<a className="mono link" href={href('/cases')}>{userId}</a>} />
            <Fact label="Transaction" value={<span className="mono">{detail.txnId ?? d?.txnId ?? DASH}</span>} />
            <Fact label="Case" value={<span className="mono">{detail.caseId}</span>} />
          </dl>
          <div className="verdictcard__rules">
            <span className="field__label">Fired rules</span>
            <Rules rules={detail.firedRules ?? d?.firedRules} />
          </div>
        </div>
        <StatusControl detail={detail} onUpdated={onUpdated} />
      </section>

      {d?.mode === 'DEGRADED' ? (
        <p className="state state--warn">
          Scored in <strong>DEGRADED</strong> mode: the ML scorer was unreachable or the circuit
          breaker was open, so rules alone produced this verdict. There is no model score and no
          SHAP attribution for this case.
        </p>
      ) : null}

      <div className="detail__grid">
        <div className="detail__col">
          <Panel
            title="Signals"
            subtitle="What fired, and the evidence the engine recorded when it fired."
          >
            {d?.signals?.length ? (
              <div className="signals">
                {d.signals.map((s, i) => (
                  <SignalCard key={`${s.code}-${i}`} signal={s} />
                ))}
              </div>
            ) : (
              <p className="state state--empty">
                No signals on this decision — it was flagged by the model score alone, or by a hard
                rule.
              </p>
            )}
          </Panel>

          <Panel
            title="Model attribution"
            subtitle="SHAP contributions to the log-odds of fraud, largest magnitude first."
          >
            <ShapChart contributions={d?.contributions ?? []} />
          </Panel>

          <Panel title="Feature vector" subtitle="Exactly what was sent to the scorer.">
            {d?.features && Object.keys(d.features).length > 0 ? (
              <dl className="kv kv--grid">
                {Object.entries(d.features).map(([k, v]) => (
                  <div className="kv__row" key={k}>
                    <dt>{humanKey(k)}</dt>
                    <dd className="mono num">{fmtValue(v)}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="state state--empty">No feature vector on this decision.</p>
            )}
          </Panel>
        </div>

        <div className="detail__col">
          <Panel
            title="Analyst report"
            subtitle="Written by the agent from read-only tool calls. Every claim must cite the evidence behind it, and a verify node checks those citations before the report is attached."
          >
            {detail.reportDoc ? (
              <AnalystReport report={detail.reportDoc} />
            ) : (
              <p className="state state--empty">
                No analyst report yet. The LangGraph agent runs asynchronously after the case is
                created and attaches a cited report when it finishes — or nothing, if it is
                disabled or it failed.
              </p>
            )}
          </Panel>

          <Panel
            title="Transaction neighbourhood"
            subtitle={`P2P transfers around ${userId}, depth 2.`}
            aside={
              <button type="button" className="btn btn--small" onClick={graph.reload}>
                Refresh
              </button>
            }
          >
            <Async
              state={graph}
              empty="The stream engine's graph read API returned nothing for this user."
            >
              {(nb) => <GraphView nb={nb} />}
            </Async>
          </Panel>

          <Panel title="User activity" subtitle="Live state from the stream engine, last 24h.">
            <Async state={history} empty="No history available for this user.">
              {(h) => <History h={h} />}
            </Async>
          </Panel>

          <Panel title="Case timeline">
            {detail.events?.length ? (
              <ol className="timeline">
                {[...detail.events]
                  .sort((a, b) => (a.at < b.at ? 1 : -1))
                  .map((ev, i) => (
                    <li className="timeline__item" key={`${ev.eventType}-${ev.at}-${i}`}>
                      <div className="timeline__head">
                        <code className="rule">{ev.eventType}</code>
                        <span className="dim" title={fmtDateTime(ev.at)}>
                          {fmtAgo(ev.at)}
                        </span>
                      </div>
                      <EventPayload ev={ev} />
                    </li>
                  ))}
              </ol>
            ) : (
              <p className="state state--empty">No events recorded for this case.</p>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="fact">
      <dt className="field__label">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function StatusControl({
  detail,
  onUpdated,
}: {
  detail: Detail;
  onUpdated: (d: Detail) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = async (status: CaseStatus) => {
    if (status === detail.status) return;
    setSaving(true);
    setError(null);
    try {
      onUpdated(await api.setStatus(detail.caseId, status));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update the status.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="statuscontrol">
      <span className="field__label">Status</span>
      <StatusBadge status={detail.status} />
      <select
        className="select"
        value={detail.status}
        disabled={saving}
        onChange={(e) => void change(e.target.value as CaseStatus)}
        aria-label="Change case status"
      >
        {CASE_STATUSES.map((s) => (
          <option key={s} value={s}>
            {titleCase(s)}
          </option>
        ))}
      </select>
      {saving ? <span className="dim">Saving…</span> : null}
      {error ? (
        <span className="state state--error state--inline" role="alert">
          {error}
        </span>
      ) : null}
      <span className="dim small">Updated {fmtAgo(detail.updatedAt)}</span>
    </div>
  );
}

/**
 * Event payloads in the timeline. Most are small flat objects and read fine as
 * a key/value list, but REPORT_ATTACHED carries the entire report document —
 * dumping that inline would drown the timeline and duplicate the report panel,
 * so it collapses to the one line that tells the reader what happened.
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
          {passed === true
            ? 'citations verified'
            : passed === false
              ? 'verification failed'
              : 'verification unknown'}
        </span>
        <span className="dim">
          {' · '}
          {r.findings.length} claim{r.findings.length === 1 ? '' : 's'}
          {' · '}
          {r.evidence.length} evidence
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
          <dt>{humanKey(k)}</dt>
          <dd className="mono">{fmtValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function History({ h }: { h: UserHistory }) {
  return (
    <>
      <dl className="kv kv--grid">
        <div className="kv__row">
          <dt>amount profile</dt>
          <dd className="mono num">
            {h.profile
              ? `n=${fmtNum(h.profile.n, 0)} · mean ${fmtMoney(h.profile.mean)} · sd ${fmtMoney(h.profile.std)}`
              : 'unavailable'}
          </dd>
        </div>
        <div className="kv__row">
          <dt>1m / 5m / 1h count</dt>
          <dd className="mono num">
            {h.windows
              ? `${fmtNum(h.windows.cnt1m, 0)} / ${fmtNum(h.windows.cnt5m, 0)} / ${fmtNum(h.windows.cnt1h, 0)}`
              : 'unavailable'}
          </dd>
        </div>
        <div className="kv__row">
          <dt>1m / 5m / 1h sum</dt>
          <dd className="mono num">
            {h.windows
              ? `${fmtMoney(h.windows.sum1m)} / ${fmtMoney(h.windows.sum5m)} / ${fmtMoney(h.windows.sum1h)}`
              : 'unavailable'}
          </dd>
        </div>
      </dl>
      {!h.profile && !h.windows ? (
        <p className="state state--warn">
          The stream engine read API is unreachable, so live profile and window state are missing.
        </p>
      ) : null}
      {h.recent?.length ? (
        <ul className="minifeed">
          {h.recent.slice(0, 12).map((r) => (
            <li key={r.txnId} className={`minifeed__row minifeed__row--${r.verdict.toLowerCase()}`}>
              <span className="mono dim">{fmtAgo(r.decidedAt)}</span>
              <VerdictPill verdict={r.verdict} />
              <span className="mono num">{fmtScore(r.mlScore)}</span>
              <Rules rules={r.firedRules} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="state state--empty">No recent decisions for this user.</p>
      )}
    </>
  );
}
