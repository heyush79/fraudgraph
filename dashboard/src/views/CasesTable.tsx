import { source } from '../data';
import { useAsync } from '../lib/useAsync';
import { caseHref, navigate } from '../lib/useHashRoute';
import { CASE_STATUSES, type CasePage, type CaseStatus, type Stats } from '../lib/types';
import { fmtDateTime, fmtInt, fmtNum, fmtScore, fmtWhen, shortId, titleCase } from '../lib/format';
import { Async, Panel, Rules, StatusBadge, VerdictPill } from '../components/Bits';

const LIMIT = 50;
const REPLAY = source.mode === 'replay';

export function CasesTable({ query }: { query: URLSearchParams }) {
  const raw = query.get('status') ?? '';
  const status = (CASE_STATUSES as readonly string[]).includes(raw) ? (raw as CaseStatus) : '';
  const offset = Math.max(0, Number(query.get('offset') ?? 0) || 0);

  const state = useAsync<CasePage>((s) => source.cases({ status, limit: LIMIT, offset }, s), [status, offset]);
  // Live: polled, since /stats counts cases the page has not seen. Replay: the manifest's.
  const stats = useAsync<Stats>((s) => source.stats(s), ['stats'], REPLAY ? undefined : 10_000);

  const st = stats.data;

  const go = (next: { status?: string; offset?: number }) => {
    const q = new URLSearchParams();
    const st = next.status ?? status;
    const off = next.offset ?? 0;
    if (st) q.set('status', st);
    if (off) q.set('offset', String(off));
    const qs = q.toString();
    navigate(`/cases${qs ? `?${qs}` : ''}`);
  };

  return (
    <div className="page">
      <Panel
        title="Cases"
        subtitle={
          REPLAY
            ? 'Every REVIEW or BLOCK decision recorded in this replay. Open one to investigate it in the console.'
            : 'Every REVIEW or BLOCK decision the case service has stored. Open one to investigate it in the console.'
        }
        aside={
          <div className="toolbar">
            <label className="field">
              <span className="label">Status</span>
              <select className="select" value={status} onChange={(e) => go({ status: e.target.value, offset: 0 })}>
                <option value="">All</option>
                {CASE_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {titleCase(s)}
                  </option>
                ))}
              </select>
            </label>
            {!REPLAY ? (
              <button type="button" className="btn btn--small" onClick={state.reload}>
                Refresh
              </button>
            ) : null}
          </div>
        }
      >
        {st ? (
          <dl className="casestats">
            <div className="casestats__item">
              <dt className="label">{REPLAY ? 'Cases in recording' : 'Cases'}</dt>
              <dd className="mono">{fmtInt(st.total)}</dd>
            </div>
            {CASE_STATUSES.map((s) => (
              <div className="casestats__item" key={s}>
                <dt className="label">{titleCase(s)}</dt>
                <dd className="mono">{fmtInt(st.byStatus?.[s] ?? 0)}</dd>
              </div>
            ))}
            {!REPLAY ? (
              <div className="casestats__item">
                <dt className="label">Opened, last hour</dt>
                <dd className="mono">
                  {fmtInt(st.last1h?.cases ?? 0)}{' '}
                  <span className="dim small">
                    ({fmtInt(st.last1h?.block ?? 0)} block, {fmtInt(st.last1h?.review ?? 0)} review)
                  </span>
                </dd>
              </div>
            ) : null}
          </dl>
        ) : null}

        <Async
          state={state}
          isEmpty={(d) => (d.items?.length ?? 0) === 0}
          empty={
            status
              ? `No cases with status ${titleCase(status)}.`
              : 'No cases yet. Flagged decisions appear here as soon as the engine emits a REVIEW or BLOCK.'
          }
        >
          {(page) => (
            <>
              <div className="tablewrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Opened</th>
                      <th>Account</th>
                      <th>Verdict</th>
                      <th className="num">Score</th>
                      <th>Status</th>
                      <th>Fired rules</th>
                      <th>Case</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((c) => (
                      <tr
                        key={c.caseId}
                        className="table__row is-link"
                        onClick={() => navigate(`/case/${encodeURIComponent(c.caseId)}`)}
                      >
                        <td title={fmtDateTime(c.createdAt)}>
                          <span className="mono dim">{fmtWhen(c.createdAt)}</span>
                        </td>
                        <td className="mono">{c.userId}</td>
                        <td>
                          <VerdictPill verdict={c.verdict} />
                        </td>
                        <td className="mono num">{fmtScore(c.mlScore)}</td>
                        <td>
                          <StatusBadge status={c.status} />
                        </td>
                        <td>
                          <Rules rules={c.firedRules} />
                        </td>
                        <td>
                          <a className="link mono" href={caseHref(c.caseId)} onClick={(e) => e.stopPropagation()}>
                            {shortId(c.caseId)}
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <nav className="pager" aria-label="Pagination">
                <button
                  type="button"
                  className="btn btn--small"
                  disabled={offset === 0}
                  onClick={() => go({ offset: Math.max(0, offset - LIMIT) })}
                >
                  Newer
                </button>
                <span className="pager__label mono">
                  {fmtNum(offset + 1, 0)}–{fmtNum(offset + page.items.length, 0)} of {fmtNum(page.total, 0)}
                </span>
                <button
                  type="button"
                  className="btn btn--small"
                  disabled={offset + page.items.length >= page.total}
                  onClick={() => go({ offset: offset + LIMIT })}
                >
                  Older
                </button>
              </nav>
            </>
          )}
        </Async>
      </Panel>
    </div>
  );
}
