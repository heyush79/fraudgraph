import { api } from '../lib/api';
import { useAsync } from '../lib/useAsync';
import { href, navigate } from '../lib/useHashRoute';
import { CASE_STATUSES, type CasePage, type CaseStatus } from '../lib/types';
import { fmtAgo, fmtDateTime, fmtNum, fmtScore, titleCase } from '../lib/format';
import { Async, Panel, Rules, StatusBadge, VerdictPill } from '../components/Bits';

const LIMIT = 50;

export function CasesTable({ query }: { query: URLSearchParams }) {
  const raw = query.get('status') ?? '';
  const status = (CASE_STATUSES as readonly string[]).includes(raw) ? (raw as CaseStatus) : '';
  const offset = Math.max(0, Number(query.get('offset') ?? 0) || 0);

  const state = useAsync<CasePage>(
    (s) => api.cases({ status, limit: LIMIT, offset }, s),
    [status, offset],
  );

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
    <Panel
      title="Cases"
      subtitle="Every REVIEW or BLOCK decision the case service persisted."
      aside={
        <div className="toolbar">
          <label className="field">
            <span className="field__label">Status</span>
            <select
              className="select"
              value={status}
              onChange={(e) => go({ status: e.target.value, offset: 0 })}
            >
              <option value="">All</option>
              {CASE_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {titleCase(s)}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn btn--small" onClick={state.reload}>
            Refresh
          </button>
        </div>
      }
    >
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
                    <th>User</th>
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
                      className="table__row is-linked"
                      onClick={() => navigate(`/cases/${c.caseId}`)}
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') navigate(`/cases/${c.caseId}`);
                      }}
                    >
                      <td title={fmtDateTime(c.createdAt)}>
                        <span className="mono dim">{fmtAgo(c.createdAt)}</span>
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
                        <a
                          className="link mono"
                          href={href(`/cases/${c.caseId}`)}
                          onClick={(e) => e.stopPropagation()}
                        >
                          {c.caseId.slice(0, 8)}
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
                ← Newer
              </button>
              <span className="pager__label mono">
                {fmtNum(offset + 1, 0)}–{fmtNum(offset + page.items.length, 0)} of{' '}
                {fmtNum(page.total, 0)}
              </span>
              <button
                type="button"
                className="btn btn--small"
                disabled={offset + page.items.length >= page.total}
                onClick={() => go({ offset: offset + LIMIT })}
              >
                Older →
              </button>
            </nav>
          </>
        )}
      </Async>
    </Panel>
  );
}
