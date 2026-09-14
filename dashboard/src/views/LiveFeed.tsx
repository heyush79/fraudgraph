import { useMemo, useState } from 'react';
import type { FeedTick, Verdict } from '../lib/types';
import type { LiveFeed as Feed } from '../lib/useLiveFeed';
import { fmtClock, fmtNum, fmtScore } from '../lib/format';
import { navigate, href } from '../lib/useHashRoute';
import { ModeTag, Panel, Rules, VerdictPill } from '../components/Bits';

type Filter = 'ALL' | 'FLAGGED' | Verdict;
const FILTERS: { key: Filter; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'FLAGGED', label: 'Flagged' },
  { key: 'BLOCK', label: 'Block' },
  { key: 'REVIEW', label: 'Review' },
  { key: 'ALLOW', label: 'Allow' },
];

export function LiveFeed({ feed }: { feed: Feed }) {
  const [filter, setFilter] = useState<Filter>('ALL');
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState<FeedTick[]>([]);

  const source = paused ? frozen : feed.ticks;
  const rows = useMemo(
    () =>
      source.filter((t) => {
        if (filter === 'ALL') return true;
        if (filter === 'FLAGGED') return t.verdict !== 'ALLOW';
        return t.verdict === filter;
      }),
    [source, filter],
  );

  const togglePause = () => {
    if (!paused) setFrozen(feed.ticks);
    setPaused((p) => !p);
  };

  return (
    <Panel
      title="Live decisions"
      subtitle={
        <>
          Every verdict the engine emits, newest first, last 200 held in memory
          {feed.received > 0 ? <> · {fmtNum(feed.received, 0)} seen this session</> : null}.
        </>
      }
      aside={
        <div className="toolbar">
          <div className="chips" role="group" aria-label="Filter by verdict">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                className={`chip ${filter === f.key ? 'is-active' : ''}`}
                onClick={() => setFilter(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <button type="button" className="btn btn--small" onClick={togglePause}>
            {paused ? 'Resume' : 'Pause'}
          </button>
          <button type="button" className="btn btn--small" onClick={feed.clear} disabled={paused}>
            Clear
          </button>
        </div>
      }
    >
      {feed.lastError && feed.state !== 'open' ? (
        <p className="state state--warn" role="status">
          {feed.lastError}
        </p>
      ) : null}

      {rows.length === 0 ? (
        <p className="state state--empty">
          {feed.state === 'open'
            ? source.length === 0
              ? 'Connected. Waiting for the first decision — start the generator with `make demo`.'
              : 'No decisions match this filter yet.'
            : feed.state === 'connecting'
              ? 'Connecting to /ws/feed…'
              : 'Not connected to /ws/feed. Retrying automatically — is the case service up on :8082?'}
        </p>
      ) : (
        <ul className="feed" aria-live="off">
          <li className="feed__row feed__row--head" aria-hidden="true">
            <span>Time</span>
            <span>User</span>
            <span>Verdict</span>
            <span>Mode</span>
            <span className="num">Score</span>
            <span>Fired rules</span>
            <span className="num">Latency</span>
          </li>
          {rows.map((t) => (
            <Row key={t.txnId} tick={t} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Row({ tick }: { tick: FeedTick }) {
  const linked = Boolean(tick.caseId);
  const open = () => {
    if (tick.caseId) navigate(`/cases/${tick.caseId}`);
  };
  return (
    <li
      className={`feed__row feed__row--${tick.verdict.toLowerCase()} ${linked ? 'is-linked' : ''}`}
      onClick={linked ? open : undefined}
      onKeyDown={
        linked
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                open();
              }
            }
          : undefined
      }
      tabIndex={linked ? 0 : undefined}
      role={linked ? 'link' : undefined}
      title={
        linked
          ? `Open case ${tick.caseId}`
          : `txn ${tick.txnId} — no case (only REVIEW and BLOCK open cases)`
      }
    >
      <span className="mono dim" data-label="Time">
        {fmtClock(tick.decidedAt)}
      </span>
      <span className="mono" data-label="User">
        {tick.userId}
      </span>
      <span data-label="Verdict">
        <VerdictPill verdict={tick.verdict} />
      </span>
      <span data-label="Mode">
        <ModeTag mode={tick.mode} />
      </span>
      <span className="mono num" data-label="Score">
        {fmtScore(tick.mlScore)}
      </span>
      <span data-label="Rules">
        <Rules rules={tick.firedRules} />
      </span>
      <span className="mono num" data-label="Latency">
        {fmtNum(tick.latencyMs, 0)} ms
        {linked ? (
          <a className="feed__case" href={href(`/cases/${tick.caseId}`)} onClick={(e) => e.stopPropagation()}>
            case →
          </a>
        ) : null}
      </span>
    </li>
  );
}
