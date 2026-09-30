import { memo, useState } from 'react';
import { source } from '../data';
import { feedStore, usePulse, useTicker, type Ticker, type TickRow } from '../lib/feedStore';
import { fmtClock, fmtClockMs, fmtInt, fmtScore } from '../lib/format';
import { useOpenableCases } from '../lib/hooks';
import { ruleFamilies } from '../lib/signals';
import { caseHref } from '../lib/useHashRoute';
import { VerdictPill } from '../components/Bits';

const REPLAY = source.mode === 'replay';
/** Only rows younger than this animate when they mount, so a filter switch never replays the flashes. */
const ANIMATE_WINDOW_MS = 1_200;

type Filter = 'ALL' | 'FLAGGED';

/**
 * The left pane: every decision as the engine makes it, newest first. The
 * list is capped at 200 rows; the flagged filter keeps its own 200, so it is
 * not the 2% of the last 200 that happened to be flagged.
 */
export function LiveFeed({ selectedCaseId }: { selectedCaseId: string | null }) {
  const live = useTicker();
  const pulse = usePulse();
  const openable = useOpenableCases();
  const [filter, setFilter] = useState<Filter>('ALL');
  const [frozen, setFrozen] = useState<Ticker | null>(null);

  const view = frozen ?? live;
  const rows = filter === 'ALL' ? view.all : view.flagged;
  const behind = frozen ? live.received - frozen.received : 0;
  const now = performance.now();

  const canOpen = (t: TickRow) =>
    Boolean(t.caseId) && t.verdict !== 'ALLOW' && (openable === null || (openable?.has(t.caseId!) ?? false));

  return (
    <section className="pane pane--feed" aria-label="Decision feed">
      <header className="pane__head">
        <h2 className="label">Decision feed</h2>
        <div className="seg" role="group" aria-label="Show">
          <button type="button" className="seg__btn" aria-pressed={filter === 'ALL'} onClick={() => setFilter('ALL')}>
            All
          </button>
          <button
            type="button"
            className="seg__btn"
            aria-pressed={filter === 'FLAGGED'}
            onClick={() => setFilter('FLAGGED')}
          >
            Flagged <span className="mono">{fmtInt(view.flagged.length)}</span>
          </button>
        </div>
        <button
          type="button"
          className="btn btn--ghost btn--small"
          onClick={() => setFrozen(frozen ? null : live)}
          aria-pressed={Boolean(frozen)}
          title={frozen ? 'Resume the feed' : 'Freeze the feed to read it'}
        >
          {frozen ? 'Resume' : 'Pause'}
        </button>
      </header>
      <p className="feed__hint">
        {frozen ? (
          <>
            Paused. <span className="mono">{fmtInt(behind)}</span> newer decision{behind === 1 ? '' : 's'} waiting.
          </>
        ) : (
          <>Every payment as the engine decides it. Click a flagged one to investigate.</>
        )}
      </p>

      <div className="pane__body feed">
        {rows.length === 0 ? (
          <p className="state state--empty">{emptyText(filter, pulse.conn, pulse.error, live.all.length)}</p>
        ) : (
          <>
            <div className="tick tick--head" aria-hidden="true">
              <span>Time</span>
              <span>Account</span>
              <span>Verdict</span>
              <span className="num">Score</span>
              <span>Signals</span>
              <span className="num">Latency</span>
            </div>
            <ul className="ticks">
              {rows.map((t) => (
                <Row
                  key={t.key}
                  t={t}
                  animate={t.animate && now - t.arrivedAt < ANIMATE_WINDOW_MS}
                  selected={t.caseId !== null && t.caseId === selectedCaseId}
                  openable={canOpen(t)}
                />
              ))}
            </ul>
          </>
        )}
      </div>
      {pulse.conn === 'closed' && !REPLAY ? (
        <p className="feed__status" role="status">
          Disconnected from the decision stream{pulse.attempt ? `, retry ${pulse.attempt}` : ''}.{' '}
          <button type="button" className="linkbtn" onClick={() => feedStore.retry()}>
            Reconnect now
          </button>
        </p>
      ) : null}
    </section>
  );
}

function emptyText(filter: Filter, conn: string, error: string | null, total: number): string {
  if (conn === 'connecting') return REPLAY ? 'Loading the recording…' : 'Connecting to the decision stream…';
  if (conn === 'closed') {
    return REPLAY
      ? (error ?? 'The recording could not be loaded.')
      : 'Not connected to the decision stream. Retrying automatically.';
  }
  if (filter === 'FLAGGED' && total > 0) {
    return REPLAY
      ? 'No flagged decisions yet in this pass of the recording.'
      : 'No flagged decisions since this page opened. They appear here the moment one is decided.';
  }
  return REPLAY ? 'The recording is starting…' : 'Connected. Waiting for the first decision.';
}

const Row = memo(function Row({
  t,
  animate,
  selected,
  openable,
}: {
  t: TickRow;
  animate: boolean;
  selected: boolean;
  openable: boolean;
}) {
  const flagged = t.verdict !== 'ALLOW';
  const cls = [
    'tick',
    `tick--${t.verdict.toLowerCase()}`,
    animate ? (flagged ? 'tick--new tick--flash' : 'tick--new') : '',
    openable ? 'is-link' : '',
    selected ? 'is-selected' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const cells = (
    <>
      <span className="tick__time" title={fmtClockMs(t.decidedAt)}>
        {fmtClock(t.decidedAt)}
      </span>
      <span className="tick__user">{t.userId}</span>
      <span className="tick__verdict">
        <VerdictPill verdict={t.verdict} />
      </span>
      <span className={t.mlScore === null ? 'tick__score num faint' : 'tick__score num'}>{fmtScore(t.mlScore)}</span>
      <span className="tick__rules" title={t.firedRules?.join(', ') || undefined}>
        {t.mode === 'DEGRADED' ? <span className="tick__degraded">rules only · </span> : null}
        {ruleFamilies(t.firedRules)}
      </span>
      <span className="tick__lat num">{Math.round(t.latencyMs)} ms</span>
    </>
  );

  if (openable && t.caseId) {
    return (
      <li>
        <a
          className={cls}
          href={caseHref(t.caseId)}
          aria-current={selected ? 'true' : undefined}
          title={`Investigate case ${t.caseId}`}
        >
          {cells}
        </a>
      </li>
    );
  }
  return (
    <li>
      <div
        className={cls}
        title={
          flagged && t.caseId && REPLAY
            ? 'This case was not recorded in the replay'
            : flagged
              ? `Case ${t.caseId ?? 'pending'}`
              : 'Allowed: only REVIEW and BLOCK decisions open cases'
        }
      >
        {cells}
      </div>
    </li>
  );
});
