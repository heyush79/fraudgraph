import { api } from '../lib/api';
import { useAsync } from '../lib/useAsync';
import { href } from '../lib/useHashRoute';
import { fmtNum, titleCase } from '../lib/format';
import type { ConnState } from '../lib/useLiveFeed';
import { CASE_STATUSES } from '../lib/types';

const CONN_LABEL: Record<ConnState, string> = {
  connecting: 'Connecting',
  open: 'Live',
  closed: 'Disconnected',
};

export function Header({
  route,
  conn,
  attempt,
  onReconnect,
}: {
  route: string;
  conn: ConnState;
  attempt: number;
  onReconnect: () => void;
}) {
  // Poll rather than derive from the feed: /stats counts cases, the feed counts
  // decisions, and only the backend knows about cases opened before this page.
  const stats = useAsync((s) => api.stats(s), [], 10_000);
  const tab = route.startsWith('/cases') ? 'cases' : 'live';

  return (
    <header className="topbar">
      <div className="topbar__row">
        <a className="brand" href={href('/live')}>
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__name">FraudGraph</span>
        </a>

        <nav className="nav" aria-label="Views">
          <a className={`nav__item ${tab === 'live' ? 'is-active' : ''}`} href={href('/live')}>
            Live feed
          </a>
          <a className={`nav__item ${tab === 'cases' ? 'is-active' : ''}`} href={href('/cases')}>
            Cases
          </a>
        </nav>

        <button
          type="button"
          className={`conn conn--${conn}`}
          onClick={onReconnect}
          title={
            conn === 'open'
              ? 'WebSocket connected to /ws/feed — click to reconnect'
              : `WebSocket ${conn}${attempt ? ` (retry ${attempt})` : ''} — click to retry now`
          }
        >
          <span className="conn__dot" aria-hidden="true" />
          {CONN_LABEL[conn]}
          {conn !== 'open' && attempt > 0 ? <span className="conn__n"> · retry {attempt}</span> : null}
        </button>
      </div>

      <div className="statbar">
        {stats.error && !stats.data ? (
          <span className="statbar__err">/stats unavailable — {stats.error.message}</span>
        ) : null}
        {stats.data ? (
          <>
            <Stat label="Cases" value={stats.data.total} strong />
            {CASE_STATUSES.map((s) => (
              <Stat
                key={s}
                label={titleCase(s)}
                value={stats.data?.byStatus?.[s] ?? 0}
                to={`/cases?status=${s}`}
                tone={s}
              />
            ))}
            <span className="statbar__sep" aria-hidden="true" />
            <Stat label="Last 1h" value={stats.data.last1h?.cases ?? 0} />
            <Stat label="Block" value={stats.data.last1h?.block ?? 0} tone="block" />
            <Stat label="Review" value={stats.data.last1h?.review ?? 0} tone="review" />
          </>
        ) : (
          <span className="statbar__err">{stats.loading ? 'Loading stats…' : ''}</span>
        )}
      </div>
    </header>
  );
}

function Stat({
  label,
  value,
  to,
  tone,
  strong,
}: {
  label: string;
  value: number;
  to?: string;
  tone?: string;
  strong?: boolean;
}) {
  const inner = (
    <>
      <span className="stat__label">{label}</span>
      <span className="stat__value mono">{fmtNum(value, 0)}</span>
    </>
  );
  const cls = `stat ${tone ? `stat--${tone.toLowerCase()}` : ''} ${strong ? 'stat--strong' : ''}`;
  return to ? (
    <a className={cls} href={href(to)}>
      {inner}
    </a>
  ) : (
    <span className={cls}>{inner}</span>
  );
}
