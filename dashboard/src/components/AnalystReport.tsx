import { useState } from 'react';
import type { ReactNode } from 'react';
import type { ReportDoc } from '../lib/types';
import {
  normalizeReport,
  prettyJson,
  shapeHint,
  violationHelp,
  violationLabel,
  type NormCitation,
  type NormEvidence,
  type NormFinding,
  type NormReport,
  type NormVerification,
} from '../lib/report';
import { DASH, fmtNum, fmtValue, humanKey, titleCase } from '../lib/format';
import { quantities, splitNumbers, supports, type Quantity } from '../lib/numbers';
import { Glyph } from './Bits';

/**
 * The analyst agent's report.
 *
 * The organising idea is that a sceptical reader must be able to check the
 * agent rather than trust it, so two things come before the prose: whether the
 * programmatic citation check passed, and a path from any single claim to the
 * raw tool output behind it. Citations are buttons that expand the cited
 * evidence inline, under the claim, with the numbers the claim quotes marked —
 * one click, no network call, and it still works in a phone column.
 */
export function AnalystReport({ report }: { report: ReportDoc }) {
  const r = normalizeReport(report);

  if (!r || r.empty) {
    return (
      <p className="state state--warn">
        A report was attached to this case but it is empty or unreadable: the agent returned no
        summary, findings or evidence. Treat the case as not investigated.
      </p>
    );
  }

  return (
    <div className="report">
      <VerificationBanner v={r.verification} report={r} />
      {r.summary ? <p className="report__summary">{r.summary}</p> : null}
      <Verdicts r={r} />
      <Findings r={r} />
      <EvidenceList evidence={r.evidence} declared={r.verification?.evidenceCount ?? null} />
    </div>
  );
}

/* ---------- verification, first ---------- */

function VerificationBanner({ v, report }: { v: NormVerification | null; report: NormReport }) {
  if (!v) {
    return (
      <div className="verify verify--unknown">
        <p className="verify__head">
          <span className="verify__title">Citations not verified</span>
        </p>
        <p className="verify__note">
          This report carries no verification block, so nothing has checked its claims against the
          evidence they cite. Read it as an unchecked draft.
        </p>
      </div>
    );
  }

  const state = v.passed === true ? 'pass' : v.passed === false ? 'fail' : 'unknown';

  return (
    <div className={`verify verify--${state}`}>
      <p className="verify__head">
        {state === 'pass' ? <Glyph name="shield" /> : null}
        <span className="verify__title">
          {state === 'pass'
            ? 'Every claim checked against its evidence'
            : state === 'fail'
              ? 'Claims failed the check, so the case was escalated'
              : 'Verification status unknown'}
        </span>
        <span className="verify__stats mono">
          {fmtCount(report.findings.length, 'claim')} kept · {fmtCount(v.toolCallsUsed, 'tool call')} ·{' '}
          {fmtCount(v.attempts, 'attempt')}
        </span>
      </p>
      <p className="verify__note">
        {state === 'pass' ? (
          <>
            Before this report was attached, code checked that each claim cites evidence that exists,
            came from a tool call that succeeded, and contains every number the claim quotes.
          </>
        ) : state === 'fail' ? (
          <>
            The checker rejected the draft twice, so the case was escalated as{' '}
            <strong>UNCERTAIN</strong> and unsupported claims were removed.{' '}
            {v.violations.length > 0
              ? 'What failed is listed below.'
              : 'No specific failures were recorded.'}
          </>
        ) : (
          <>The verification block does not say whether the check passed. Do not assume the claims are supported.</>
        )}
      </p>
      <Violations v={v} report={report} />
    </div>
  );
}

function fmtCount(n: number | null, noun: string): string {
  if (n === null) return `${DASH} ${noun}s`;
  return `${fmtNum(n, 0)} ${noun}${n === 1 ? '' : 's'}`;
}

function Violations({ v, report }: { v: NormVerification; report: NormReport }) {
  if (v.violations.length === 0) return null;
  return (
    <ol className="viol">
      {v.violations.map((x, i) => {
        const help = violationHelp(x.kind);
        // The claim may be gone: violations are the union across attempts and
        // an escalated report has its unsupported findings removed.
        const stripped = x.findingIndex !== null && x.claim === null;
        return (
          <li className="viol__item" key={i}>
            <div className="viol__head">
              <code className="viol__kind">{x.kind ?? 'unknown'}</code>
              <span className="viol__label">{violationLabel(x.kind)}</span>
              <span className="viol__where mono">
                {x.findingIndex === null
                  ? 'whole report'
                  : `claim ${fmtNum(x.findingIndex + 1, 0)}${stripped ? ', removed' : ''}`}
              </span>
            </div>
            {x.detail ? <p className="viol__detail">{x.detail}</p> : null}
            {x.claim ? (
              <p className="viol__claim">
                <span className="label">Claim</span> &ldquo;{x.claim}&rdquo;
              </p>
            ) : stripped ? (
              <p className="viol__claim dim">
                That claim is no longer in the report: it was removed when the report was escalated
                {report.findings.length === 0 ? ', which left no claims at all' : ''}.
              </p>
            ) : null}
            {help ? <p className="viol__help dim">{help}</p> : null}
          </li>
        );
      })}
    </ol>
  );
}

/* ---------- fraud type / confidence / action ---------- */

function Verdicts({ r }: { r: NormReport }) {
  const action = r.action;
  // CONFIRM_BLOCK reads as the block colour, RELEASE as allow, ESCALATE as
  // review: the same three colours as the verdicts, so there is one palette.
  const tone =
    action === 'CONFIRM_BLOCK' ? 'block' : action === 'RELEASE' ? 'allow' : action === 'ESCALATE' ? 'review' : 'none';
  const pct = r.confidence === null ? null : Math.round(r.confidence * 100);

  return (
    <dl className="report__verdicts">
      <div className="report__verdict">
        <dt className="label">Fraud type</dt>
        <dd>
          <span className={`ftype ftype--${(r.fraudType ?? 'none').toLowerCase()}`}>{r.fraudType ?? 'not stated'}</span>
        </dd>
      </div>
      <div className="report__verdict">
        <dt className="label">Confidence</dt>
        <dd>
          {r.confidence === null ? (
            <span className="dim">not stated</span>
          ) : (
            <span className="conf">
              <span className="conf__num mono">{r.confidence.toFixed(2)}</span>
              <span className="conf__track" title={`${pct}%`} aria-hidden="true">
                <span className="conf__bar" style={{ width: `${pct}%` }} />
              </span>
            </span>
          )}
        </dd>
      </div>
      <div className="report__verdict">
        <dt className="label">Recommends</dt>
        <dd>
          <span className={`action action--${tone}`}>{action ? titleCase(action) : 'not stated'}</span>
        </dd>
      </div>
    </dl>
  );
}

/* ---------- findings and their citations ---------- */

function Findings({ r }: { r: NormReport }) {
  if (r.findings.length === 0) {
    const failed = r.verification?.passed === false;
    return (
      <p className={failed ? 'state state--warn' : 'state state--empty'}>
        {failed
          ? 'No findings survived verification. Every claim the agent wrote was unsupported and was removed, so the failures above are the whole result.'
          : 'The agent produced no findings for this case.'}
      </p>
    );
  }

  return (
    <div className="report__section">
      <p className="report__h label">
        Findings <span className="label__aside">click a citation to see the evidence</span>
      </p>
      <ol className="findings">
        {r.findings.map((f) => (
          <FindingRow key={f.index} f={f} />
        ))}
      </ol>
    </div>
  );
}

function FindingRow({ f }: { f: NormFinding }) {
  // One open citation per claim: the reader is checking one number at a time.
  const [open, setOpen] = useState<number | null>(null);
  const shown = open === null ? null : f.citations[open];

  return (
    <li className="finding">
      <p className="finding__claim">
        {f.claim ?? <span className="dim">(empty claim)</span>}{' '}
        {f.uncited ? (
          <span className="cite cite--none" title="This claim cites no evidence at all.">
            no citation
          </span>
        ) : (
          f.citations.map((c, i) => (
            <CiteChip
              key={i}
              c={c}
              open={open === i}
              onToggle={() => setOpen(open === i ? null : i)}
              panelId={`cite-panel-${f.index}`}
            />
          ))
        )}
      </p>
      {shown ? (
        <div className="finding__evidence" id={`cite-panel-${f.index}`}>
          <CitationBody c={shown} quoted={quantities(f.claim ?? '')} />
        </div>
      ) : null}
    </li>
  );
}

export function CiteChip({
  c,
  open,
  onToggle,
  panelId,
}: {
  c: NormCitation;
  open: boolean;
  onToggle: () => void;
  panelId: string;
}) {
  const label = c.ref === null ? fmtValue(c.raw) : String(c.ref);
  const title =
    c.status === 'ok'
      ? `Evidence ${label}: ${c.entry?.tool ?? 'unknown tool'}. Click to inspect.`
      : c.status === 'failed'
        ? `Evidence ${label} is a failed tool call and cannot support a claim. Click for the error.`
        : `Evidence ${label} does not exist in this evidence list.`;

  return (
    <button
      type="button"
      className={open ? `cite cite--${c.status} is-open` : `cite cite--${c.status}`}
      onClick={onToggle}
      aria-expanded={open}
      aria-controls={open ? panelId : undefined}
      title={title}
    >
      <span className="cite__ref mono">{label}</span>
      {c.entry?.tool ? <span className="cite__tool">{toolWords(c.entry.tool)}</span> : null}
      {c.status === 'failed' ? <span className="cite__flag">failed</span> : null}
      {c.status === 'missing' ? <span className="cite__flag">missing</span> : null}
    </button>
  );
}

const TOOL_WORDS: Record<string, string> = {
  decision: 'decision',
  get_case: 'case',
  get_user_history: 'history',
  get_window_counts: 'window counts',
  get_graph_neighborhood: 'graph',
  find_similar_cases: 'similar cases',
};

/** "get_window_counts" → "window counts": the chip is a label, the card says the real name. */
export function toolWords(tool: string): string {
  return TOOL_WORDS[tool] ?? tool.replace(/^get_/, '').replace(/_/g, ' ');
}

export function CitationBody({ c, quoted }: { c: NormCitation; quoted: Quantity[] }) {
  if (!c.entry) {
    return (
      <p className="state state--error">
        This claim cites evidence{' '}
        <span className="mono">{c.ref === null ? fmtValue(c.raw) : `#${c.ref}`}</span>, which does not
        exist. Nothing supports the claim.
      </p>
    );
  }
  return (
    <>
      {c.entry.failed ? (
        <p className="state state--error">
          The cited tool call failed, so it carries no data. A claim resting on it is unsupported.
        </p>
      ) : null}
      <EvidenceCard e={c.entry} defaultOpen quoted={quoted} />
    </>
  );
}

/* ---------- the full evidence array ---------- */

function EvidenceList({ evidence, declared }: { evidence: NormEvidence[]; declared: number | null }) {
  if (evidence.length === 0) {
    return (
      <p className="state state--empty">
        {declared && declared > 0
          ? `Verification counted ${declared} evidence entries, but none were attached to the report.`
          : 'No evidence was attached to this report.'}
      </p>
    );
  }
  const failed = evidence.filter((e) => e.failed).length;
  return (
    <details className="evlist">
      <summary className="evlist__summary">
        <span className="label">All evidence</span>{' '}
        <span className="dim small">
          {evidence.length} tool call{evidence.length === 1 ? '' : 's'}
          {failed > 0 ? `, ${failed} failed` : ''}
        </span>
      </summary>
      <div className="evlist__items">
        {evidence.map((e) => (
          <EvidenceCard key={`${e.pos}-${e.index}`} e={e} />
        ))}
      </div>
    </details>
  );
}

/**
 * One evidence entry. Collapsed in the browsable list, open when reached from
 * a citation. Payloads are arbitrary nested JSON and some are large, so the
 * body is a scroll-capped monospace block. When `quoted` is given, every
 * number in the payload that matches a quantity the claim quotes is marked.
 */
export function EvidenceCard({
  e,
  defaultOpen = false,
  quoted = [],
}: {
  e: NormEvidence;
  defaultOpen?: boolean;
  quoted?: Quantity[];
}) {
  return (
    <details className={`ev ${e.failed ? 'ev--failed' : ''}`} open={defaultOpen}>
      <summary className="ev__head">
        <span className="ev__index mono">#{e.index}</span>
        <span className="ev__tool mono">{e.tool ?? 'unknown tool'}</span>
        {e.failed ? (
          <span className="ev__badge ev__badge--err">error</span>
        ) : (
          <span className="ev__hint dim">{shapeHint(e.hasPayload ? e.payload : undefined)}</span>
        )}
      </summary>
      <div className="ev__body">
        {e.hasArgs ? (
          <Row label="Arguments">
            <Args args={e.args} />
          </Row>
        ) : null}
        {e.failed ? (
          <Row label="Error">
            <p className="ev__error">{e.error}</p>
          </Row>
        ) : e.hasPayload ? (
          <Row label={quoted.length > 0 ? 'Result, with the quoted numbers marked' : 'Result'}>
            <pre className="ev__json mono">
              <MarkedJson text={prettyJson(e.payload)} quoted={quoted} />
            </pre>
          </Row>
        ) : (
          <Row label="Result">
            <span className="dim">The entry has neither a result nor an error, so it proves nothing.</span>
          </Row>
        )}
      </div>
    </details>
  );
}

function MarkedJson({ text, quoted }: { text: string; quoted: Quantity[] }) {
  if (quoted.length === 0) return <>{text}</>;
  return (
    <>
      {splitNumbers(text).map((part, i) =>
        part.value !== null && supports(part.value, quoted) ? (
          <mark className="hit" key={i}>
            {part.text}
          </mark>
        ) : (
          part.text
        ),
      )}
    </>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="ev__row">
      <span className="label">{label}</span>
      <div className="ev__rowbody">{children}</div>
    </div>
  );
}

/** Tool args are small flat objects in practice, but fall back to JSON if not. */
function Args({ args }: { args: unknown }) {
  if (args !== null && typeof args === 'object' && !Array.isArray(args)) {
    const entries = Object.entries(args as Record<string, unknown>);
    if (entries.length === 0) return <span className="dim">none</span>;
    if (entries.every(([, v]) => v === null || typeof v !== 'object')) {
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
  }
  return <pre className="ev__json mono">{prettyJson(args)}</pre>;
}
