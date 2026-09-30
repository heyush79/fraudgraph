import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { source } from '../data';
import { chatStore, useAskUnsupported, useChat, useCooldownUntil, type ChatEntry } from '../lib/chatStore';
import { fmtMs, shortId } from '../lib/format';
import { useAgentStatus, useManifest, useNow } from '../lib/hooks';
import { quantities } from '../lib/numbers';
import { suggestedQuestions } from '../lib/questions';
import { normalizeEvidenceList, resolveCitations } from '../lib/report';
import type { AskResponse, AskStep, CaseDetail, RemovedClaim } from '../lib/types';
import { useAsync } from '../lib/useAsync';
import { CitationBody, CiteChip } from '../components/AnalystReport';
import { Glyph } from '../components/Bits';

const REPLAY = source.mode === 'replay';

/**
 * "Ask the analyst": questions about the selected case, answered sentence by
 * sentence with citations. The answer is only ever what survived the agent's
 * verifier; what the verifier removed is disclosed underneath, collapsed, so
 * the guard is visible without the answer looking broken.
 */
export function AskAnalyst({
  caseId,
  detail,
  open,
  onClose,
}: {
  caseId: string | null;
  detail: CaseDetail | null;
  /** Below 1100 px the pane is a drawer; this says whether it is showing. */
  open: boolean;
  onClose: () => void;
}) {
  const agent = useAgentStatus();
  const manifest = useManifest();
  const entries = useChat(caseId);
  const cooldownUntil = useCooldownUntil();
  const unsupported = useAskUnsupported();
  const pending = entries.some((e) => e.status === 'pending');
  const now = useNow(1_000, pending || cooldownUntil > Date.now());
  const recorded = useAsync(
    (s) => (caseId ? source.recordedQuestions(caseId, s) : Promise.resolve(null)),
    [caseId ?? ''],
  );

  const [draft, setDraft] = useState('');
  const logRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => setDraft(''), [caseId]);

  // Keep the newest exchange in view: its question at the top of the log.
  const lastId = entries.length ? entries[entries.length - 1].id : null;
  const lastStatus = entries.length ? entries[entries.length - 1].status : null;
  useEffect(() => {
    const log = logRef.current;
    if (!log || lastId === null) return;
    const el = log.querySelector<HTMLElement>(`[data-turn="${lastId}"]`);
    if (el) log.scrollTop = Math.max(0, el.offsetTop - 8);
  }, [lastId, lastStatus]);

  // A 503 means the model went away: re-check health so the input says so.
  const lastError = entries.length ? entries[entries.length - 1].error : null;
  useEffect(() => {
    if (lastError?.kind === 'offline') agent.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastError]);

  // Drawer: Escape closes it, and focus moves into it when it opens.
  useEffect(() => {
    if (!open) return undefined;
    closeRef.current?.focus();
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const status = agent.data;
  const cooldownLeft = Math.max(0, Math.ceil((cooldownUntil - now) / 1_000));
  const agentDown = !REPLAY && (status?.state === 'down' || unsupported);
  const checking = !REPLAY && !status;
  const fixture = status?.state === 'up' && status.fixture;

  const rules = detail?.firedRules ?? detail?.decisionDoc?.firedRules ?? null;
  // Suggestions are for questions not yet asked here; an asked one stays in the log above.
  const asked = new Set(entries.filter((e) => e.status !== 'error').map((e) => e.question.toLowerCase()));
  const questions = (REPLAY ? (recorded.data ?? []) : detail ? suggestedQuestions(rules) : []).filter(
    (q) => !asked.has(q.toLowerCase()),
  );
  const blocked = !caseId || pending || cooldownLeft > 0 || agentDown || checking;
  const canType = !REPLAY && !blocked;

  const ask = (q: string) => {
    if (!caseId || blocked || !q.trim()) return;
    chatStore.ask(source, caseId, q);
    setDraft('');
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    ask(draft);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      ask(draft);
    }
  };

  const model = REPLAY ? (manifest.data?.agentModel ?? null) : status?.state === 'up' ? status.model : null;

  return (
    <aside
      className={`pane pane--chat${open ? ' is-open' : ''}`}
      aria-label="Ask the analyst"
      role={open ? 'dialog' : undefined}
      aria-modal={open ? true : undefined}
    >
      <header className="pane__head">
        <h2 className="label">Ask the analyst</h2>
        <span className="pane__meta">
          {fixture ? (
            <span className="tag tag--fixture" title="Development fixture: templated answers, no model is called">
              DEV FIXTURE
            </span>
          ) : model ? (
            <span className="mono faint" title="The model behind the analyst">
              {model}
            </span>
          ) : null}
        </span>
        <button ref={closeRef} type="button" className="btn btn--ghost btn--small drawer-close" onClick={onClose}>
          <Glyph name="close" /> Close
        </button>
      </header>

      <p className="chat__scope">
        {caseId ? (
          <>
            About case <span className="mono">{shortId(caseId)}</span>
            {detail ? (
              <>
                {' '}
                · account <span className="mono">{detail.userId}</span>
              </>
            ) : null}
          </>
        ) : (
          'No case selected'
        )}
      </p>

      <div className="pane__body chat__log" ref={logRef} aria-live="polite">
        {!caseId ? (
          <p className="chat__intro">Pick a flagged decision in the feed to ask about it.</p>
        ) : entries.length === 0 ? (
          <div className="chat__intro">
            <p>
              Ask about this case in plain English. The analyst answers only from evidence it gathers
              through read-only tools, and cites it for every sentence.
            </p>
            <p className="dim">
              Before you see an answer, code checks each number it quotes against the evidence it cites.
              Sentences that fail are removed, and the answer says so.
            </p>
          </div>
        ) : (
          entries.map((e) => (
            <Turn
              key={e.id}
              entry={e}
              now={now}
              cooldownLeft={cooldownLeft}
              onRetry={() => ask(e.question)}
              canRetry={!blocked}
            />
          ))
        )}
      </div>

      <footer className="chat__composer">
        {caseId && questions.length > 0 ? (
          <div className="chat__suggest" role="group" aria-label="Suggested questions">
            {questions.map((q) => (
              <button
                key={q}
                type="button"
                className="qchip"
                disabled={blocked}
                onClick={() => ask(q)}
                title={REPLAY ? 'A question recorded with its answer' : 'Ask this'}
              >
                {q}
              </button>
            ))}
          </div>
        ) : null}
        <form className="chat__form" onSubmit={onSubmit}>
          <label className="sr-only" htmlFor="ask-input">
            Your question about this case
          </label>
          <textarea
            id="ask-input"
            className="chat__input"
            rows={2}
            value={draft}
            disabled={!canType}
            placeholder={REPLAY ? 'Free-form questions work in live mode' : 'Ask about this case…'}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            maxLength={500}
          />
          <button type="submit" className="btn btn--primary" disabled={!canType || !draft.trim()}>
            Ask
          </button>
        </form>
        <p className="chat__note">
          {composerNote({
            caseId,
            replay: REPLAY,
            recordedCount: recorded.data?.length ?? null,
            checking,
            downReason: unsupported ? 'unsupported' : status?.state === 'down' ? status.reason : null,
            cooldownLeft,
            pending,
            fixture: Boolean(fixture),
          })}
        </p>
      </footer>
    </aside>
  );
}

function composerNote(s: {
  caseId: string | null;
  replay: boolean;
  recordedCount: number | null;
  checking: boolean;
  downReason: 'no_model' | 'unreachable' | 'unsupported' | null;
  cooldownLeft: number;
  pending: boolean;
  fixture: boolean;
}): string {
  if (!s.caseId) return 'Select a flagged decision to ask about it.';
  if (s.replay) {
    return s.recordedCount === 0
      ? 'No questions were recorded for this case. Free-form questions work in live mode.'
      : 'This replay answers the questions recorded for this case. Free-form questions work in live mode.';
  }
  if (s.checking) return 'Checking whether the analyst is available…';
  if (s.downReason === 'no_model') return 'The analyst is offline in this deployment; everything else still works.';
  if (s.downReason === 'unreachable') return 'The analyst cannot be reached from this deployment; everything else still works.';
  if (s.downReason === 'unsupported') return 'The analyst in this deployment does not take questions yet; everything else still works.';
  if (s.cooldownLeft > 0) {
    return `The public demo is rate-limited to protect a free API quota; try again in ${s.cooldownLeft} s.`;
  }
  if (s.pending) return 'The analyst is working. Answers take a few seconds.';
  if (s.fixture) return 'Development fixture: answers are templates filled from the case, no model is called.';
  return 'Enter to send, Shift+Enter for a new line. Answers take a few seconds.';
}

/* ---------- one exchange ---------- */

function Turn({
  entry,
  now,
  cooldownLeft,
  onRetry,
  canRetry,
}: {
  entry: ChatEntry;
  now: number;
  cooldownLeft: number;
  onRetry: () => void;
  canRetry: boolean;
}) {
  return (
    <article className="turn" data-turn={entry.id}>
      <p className="turn__q">
        <span className="label">You</span>
        <span>{entry.question}</span>
      </p>
      {entry.status === 'pending' ? (
        <p className="turn__pending">
          <span className="label">Analyst</span>
          <span>
            Gathering evidence and drafting
            {/* A per-second counter inside a live region would be read out every second. */}
            <span aria-hidden="true">
              {' '}
              · <span className="mono">{Math.max(0, Math.floor((now - entry.askedAt) / 1_000))} s</span>
            </span>
          </span>
        </p>
      ) : entry.status === 'error' && entry.error ? (
        <TurnError entry={entry} cooldownLeft={cooldownLeft} onRetry={onRetry} canRetry={canRetry} />
      ) : entry.response ? (
        <Answer r={entry.response} id={entry.id} />
      ) : null}
    </article>
  );
}

function TurnError({
  entry,
  cooldownLeft,
  onRetry,
  canRetry,
}: {
  entry: ChatEntry;
  /** Seconds left on the rate limit, which is per visitor, not per question. */
  cooldownLeft: number;
  onRetry: () => void;
  canRetry: boolean;
}) {
  const err = entry.error!;
  let text: string;
  let retry = false;
  switch (err.kind) {
    case 'not_found':
      text = 'This case no longer exists, so there is nothing to ask about.';
      break;
    case 'rate_limited':
      text =
        cooldownLeft > 0
          ? `The public demo is rate-limited to protect a free API quota; try again in ${cooldownLeft} s.`
          : 'The public demo is rate-limited to protect a free API quota. You can ask again now.';
      retry = cooldownLeft === 0;
      break;
    case 'offline':
      text = 'The analyst is offline in this deployment; everything else still works.';
      break;
    case 'unreachable':
      text = `${err.message} Everything else on this page still works.`;
      retry = true;
      break;
    case 'not_recorded':
      text = 'That question was not recorded for this case. Free-form questions work in live mode.';
      break;
    case 'unsupported':
      text = 'The analyst in this deployment does not take questions yet. Its reports, and everything else here, still work.';
      break;
    default:
      text = `The analyst could not answer: ${err.message}`;
      retry = true;
  }
  return (
    <div className="turn__error" role="alert">
      <span className="label">Analyst</span>
      <p>{text}</p>
      {retry ? (
        <button type="button" className="btn btn--small" onClick={onRetry} disabled={!canRetry}>
          Ask again
        </button>
      ) : null}
    </div>
  );
}

/* ---------- the answer ---------- */

function Answer({ r, id }: { r: AskResponse; id: number }) {
  const evidence = useMemo(() => normalizeEvidenceList(r.evidence), [r.evidence]);
  const [open, setOpen] = useState<{ s: number; c: number } | null>(null);

  return (
    <div className="answer">
      <p className="label">Analyst</p>
      {r.answer.length === 0 ? (
        <p className="answer__none">
          The analyst could not produce an answer it could support with evidence, so it gives none
          rather than guess.
        </p>
      ) : (
        <ol className="answer__sentences">
          {r.answer.map((s, i) => {
            const cites = resolveCitations(s.refs, evidence);
            const isOpen = open?.s === i;
            const shown = isOpen ? cites[open.c] : null;
            const panelId = `ans-${id}-${i}`;
            return (
              <li key={i} className={isOpen ? 'sentence is-open' : 'sentence'}>
                <span className="sentence__text">{s.text}</span>{' '}
                {cites.length === 0 ? (
                  <span className="cite cite--none">no citation</span>
                ) : (
                  cites.map((c, j) => (
                    <CiteChip
                      key={j}
                      c={c}
                      open={isOpen && open.c === j}
                      onToggle={() => setOpen(isOpen && open.c === j ? null : { s: i, c: j })}
                      panelId={panelId}
                    />
                  ))
                )}
                {!s.verified ? <span className="sentence__flag">not verified</span> : null}
                {shown ? (
                  <div className="sentence__evidence" id={panelId}>
                    <CitationBody c={shown} quoted={quantities(s.text)} />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
      {r.removed.length > 0 ? <Removed removed={r.removed} /> : null}
      {r.note ? <p className="answer__note">{r.note}</p> : null}
      <Trace steps={r.steps} latencyMs={r.latencyMs} />
      <p className="answer__foot mono">
        {[
          r.model || 'model not stated',
          fmtMs(r.latencyMs),
          r.mode === 'replay' ? 'recorded answer' : null,
          r.cached && r.mode !== 'replay' ? 'cached answer' : null,
        ]
          .filter(Boolean)
          .join(' · ')}
      </p>
    </div>
  );
}

/**
 * The verifier's removals. Driven by `removed` alone (contract §2): the
 * violations list also holds rejections a rewrite later fixed.
 */
function Removed({ removed }: { removed: RemovedClaim[] }) {
  const n = removed.length;
  return (
    <details className="removed">
      <summary className="removed__summary">
        <Glyph name="shield" />
        <span className="removed__title">
          The verifier removed {n === 1 ? '1 unsupported claim' : `${n} unsupported claims`}
        </span>
        <span className="removed__toggle" aria-hidden="true" />
      </summary>
      <div className="removed__body">
        <p className="removed__explain">
          Every sentence must cite evidence, and every number in it must appear in that evidence.{' '}
          {n === 1 ? 'This sentence did not hold up, so it was' : 'These sentences did not hold up, so they were'}{' '}
          left out of the answer:
        </p>
        <ul className="removed__list">
          {removed.map((c, i) => (
            <li key={i} className="removed__item">
              {c.text ? (
                <p className="removed__claim">
                  <del>{c.text}</del>
                </p>
              ) : null}
              {c.reason ? (
                <p className="removed__reason">
                  <span className="label">Why</span> {c.reason}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

const STEP_KIND: Record<string, string> = {
  evidence: 'load',
  tool: 'tool',
  draft: 'model',
  verify: 'check',
};

function Trace({ steps, latencyMs }: { steps: AskStep[]; latencyMs: number }) {
  if (steps.length === 0) return null;
  return (
    <details className="trace">
      <summary className="trace__summary">
        How it answered{' '}
        <span className="mono faint">
          {steps.length} step{steps.length === 1 ? '' : 's'} · {fmtMs(latencyMs)}
        </span>
      </summary>
      <ol className="trace__steps">
        {steps.map((s, i) => (
          <li key={i} className={`trace__step${s.detail ? ' trace__step--failed' : ''}`}>
            <span className="trace__kind mono">{STEP_KIND[s.kind] ?? s.kind}</span>
            <span className="trace__label">
              <span className={s.kind === 'tool' ? 'mono' : undefined}>{s.label}</span>
              {s.detail ? <span className="trace__detail">{s.detail}</span> : null}
            </span>
            <span className="trace__ms mono">{typeof s.ms === 'number' ? fmtMs(s.ms) : ''}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}
