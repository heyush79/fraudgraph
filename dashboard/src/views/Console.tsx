import { useCallback, useEffect, useState } from 'react';
import { source } from '../data';
import { parseTime } from '../lib/format';
import { useDefaultCaseId } from '../lib/hooks';
import type { CaseDetail as Detail } from '../lib/types';
import { useAsync } from '../lib/useAsync';
import { Glyph } from '../components/Bits';
import { IntroStrip } from '../components/IntroStrip';
import { AskAnalyst } from './AskAnalyst';
import { CaseDetail, REPORT_WAIT_MS } from './CaseDetail';
import { LiveFeed } from './LiveFeed';

/** How often a young case without a report is re-read, so the report appears when the agent attaches it. */
const REPORT_POLL_MS = 5_000;

/**
 * The one screen: the decision feed, the selected case, and the analyst chat
 * about that case. At #/ a default case is shown so the screen is never half
 * empty; #/case/{id} selects one explicitly.
 */
export function Console({ caseId }: { caseId: string | null }) {
  const fallback = useDefaultCaseId();
  const selected = caseId ?? fallback.caseId;
  const [drawer, setDrawer] = useState(false);
  const closeDrawer = useCallback(() => setDrawer(false), []);
  const openDrawer = useCallback(() => setDrawer(true), []);

  const [pollMs, setPollMs] = useState<number | undefined>(undefined);
  const detail = useAsync<Detail>(
    (s) => (selected ? source.caseDetail(selected, s) : new Promise<Detail>(() => {})),
    [selected ?? ''],
    pollMs,
  );

  // Live only: a case opened in the last few minutes may still be waiting for
  // its analyst report. Re-read it until the report lands.
  const data = detail.data;
  useEffect(() => {
    const waiting =
      source.mode === 'live' &&
      data !== null &&
      !data.reportDoc &&
      Date.now() - parseTime(data.createdAt) < REPORT_WAIT_MS;
    setPollMs(waiting ? REPORT_POLL_MS : undefined);
  }, [data]);

  // The drawer is modal below 1100 px: keep the page behind it still.
  useEffect(() => {
    document.body.classList.toggle('has-drawer', drawer);
    return () => document.body.classList.remove('has-drawer');
  }, [drawer]);

  return (
    <div className="consolewrap">
      <IntroStrip selectedCaseId={selected} />
      <div className="console">
        <LiveFeed selectedCaseId={selected} />
        <CaseDetail caseId={selected} state={detail} isDefault={!caseId} onAsk={openDrawer} />
        <AskAnalyst caseId={selected} detail={detail.data} open={drawer} onClose={closeDrawer} />
      </div>
      {drawer ? <button type="button" className="scrim" aria-label="Close the analyst" onClick={closeDrawer} /> : null}
      {!drawer && selected ? (
        <button type="button" className="askfab" onClick={openDrawer}>
          <Glyph name="chat" /> Ask the analyst
        </button>
      ) : null}
    </div>
  );
}
