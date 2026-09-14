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

/**
 * The analyst agent's report.
 *
 * The organising idea is that a sceptical reader must be able to check the
 * agent rather than trust it, so two things come before the prose: whether the
 * programmatic citation check passed, and a path from any single claim to the
 * raw tool output behind it. Citations are therefore buttons that expand the
 * cited evidence inline, under the claim — one click, no scrolling away from
 * the sentence being checked, no network call, and it still works in a phone
 * column where a side-by-side or a popover would not.
 */
export function AnalystReport({ report }: { report: ReportDoc }) {
  const r = normalizeReport(report);

  if (!r || r.empty) {
    return (
      <p className="state state--warn">
        A report was attached to this case but it is empty or unreadable — the agent returned no
        summary, findings or evidence. Treat the case as un-investigated.
      </p>
    );
  }

  return (
    <div className="report">
      <VerificationBanner v={r.verification} report={r} />
      <Verdicts r={r} />
      {r.summary ? (
        <p className="report__summary">{r.summary}</p>
      ) : (
        <p className="report__summary dim">The agent wrote no summary.</p>
      )}
      <Findings r={r} />
      <EvidenceList evidence={r.evidence} declared={r.verification?.evidenceCount ?? null} />
    </div>
  );
}

/* ---------- verification, first and loudest ---------- */

function VerificationBanner({ v, report }: { v: NormVerification | null; report: NormReport }) {
  if (!v) {
    return (
      <div className="verify verify--unknown">
        <p className="verify__head">
          <span className="verify__mark" aria-hidden="true">
            ?
          </span>
          <span className="verify__title">Citations not verified</span>
        </p>
        <p className="verify__note">
          This report carries no verification block, so nothing has checked that its claims are
          backed by the evidence it cites. Read it as an unchecked draft.
        </p>
      </div>
    );
  }

  const state = v.passed === true ? 'pass' : v.passed === false ? 'fail' : 'unknown';
  const title =
    state === 'pass'
      ? 'Citations verified'
      : state === 'fail'
        ? 'Verification failed — escalated'
        : 'Verification status unknown';
  const mark = state === 'pass' ? '✓' : state === 'fail' ? '!' : '?';

  return (
    <div className={`verify verify--${state}`}>
      <p className="verify__head">
        <span className="verify__mark" aria-hidden="true">
          {mark}
        </span>
        <span className="verify__title">{title}</span>
      </p>
      <p className="verify__note">
        {state === 'pass' ? (
          <>
            Every claim below cites an evidence entry that exists, came from a tool call that
            succeeded, and contains the numbers the claim quotes.
          </>
        ) : state === 'fail' ? (
          <>
            The checker rejected this report twice, so the case was escalated as{' '}
            <strong>UNCERTAIN</strong> and unsupported claims were stripped out.{' '}
            {v.violations.length > 0
              ? 'The failures are listed below.'
              : 'No specific violations were recorded, which is itself suspect.'}
          </>
        ) : (
          <>
            The verification block did not say whether the check passed. Do not assume the claims
            below are supported.
          </>
        )}
      </p>
      <Violations v={v} report={report} />
      <dl className="verify__stats">
        <Stat label="Attempts" value={v.attempts} />
        <Stat label="Tool calls" value={v.toolCallsUsed} />
        <Stat label="Evidence entries" value={v.evidenceCount} />
        <Stat label="Claims kept" value={report.findings.length} />
      </dl>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="verify__stat">
      <dt>{label}</dt>
      <dd className="mono">{value === null ? DASH : fmtNum(value, 0)}</dd>
    </div>
  );
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
                  : `claim #${fmtNum(x.findingIndex + 1, 0)}${stripped ? ' · removed' : ''}`}
              </span>
            </div>
            {x.detail ? <p className="viol__detail">{x.detail}</p> : null}
            {x.claim ? (
              <p className="viol__claim">
                <span className="field__label">Claim</span> “{x.claim}”
              </p>
            ) : stripped ? (
              <p className="viol__claim dim">
                That claim is not in the report any more — it was removed when the report was
                escalated{report.findings.length === 0 ? ', which left no claims at all' : ''}.
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
  // review — the same three colours the verdict pills use, so an analyst does
  // not learn a second palette.
  const tone =
    action === 'CONFIRM_BLOCK'
      ? 'block'
      : action === 'RELEASE'
        ? 'allow'
        : action === 'ESCALATE'
          ? 'review'
          : 'none';
  const pct = r.confidence === null ? null : Math.round(r.confidence * 100);

  return (
    <dl className="report__verdicts">
      <div className="report__verdict">
        <dt className="field__label">Fraud type</dt>
        <dd>
          <span className={`ftype ftype--${(r.fraudType ?? 'none').toLowerCase()}`}>
            {r.fraudType ?? 'not stated'}
          </span>
        </dd>
      </div>
      <div className="report__verdict">
        <dt className="field__label">Confidence</dt>
        <dd>
          {r.confidence === null ? (
            <span className="dim">not stated</span>
          ) : (
            <span className="conf">
              <span className="conf__num mono">{r.confidence.toFixed(2)}</span>
              <span className="conf__track" title={`${pct}%`}>
                <span className="conf__bar" style={{ width: `${pct}%` }} />
              </span>
            </span>
          )}
        </dd>
      </div>
      <div className="report__verdict">
        <dt className="field__label">Recommended action</dt>
        <dd>
          <span className={`action action--${tone}`}>
            {action ? titleCase(action) : 'not stated'}
          </span>
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
      <div className="report__section">
        <h3 className="report__h">Findings</h3>
        <p className={failed ? 'state state--warn' : 'state state--empty'}>
          {failed
            ? 'No findings survived verification. Every claim the agent wrote was unsupported and was stripped out, so there is nothing here to review — the violations above are the whole result.'
            : 'The agent produced no findings for this case.'}
        </p>
      </div>
    );
  }

  return (
    <div className="report__section">
      <h3 className="report__h">
        Findings <span className="dim small">· click a citation to see the evidence behind it</span>
      </h3>
      <ol className="findings">
        {r.findings.map((f) => (
          <FindingRow key={f.index} f={f} />
        ))}
      </ol>
    </div>
  );
}

function FindingRow({ f }: { f: NormFinding }) {
  // One open citation per claim: the reader is checking one number at a time,
  // and keeping several payloads expanded under one sentence buries it.
  const [open, setOpen] = useState<number | null>(null);
  const shown = open === null ? null : f.citations[open];

  return (
    <li className="finding">
      <p className="finding__claim">{f.claim ?? <span className="dim">(empty claim)</span>}</p>
      <div className="finding__cites">
        <span className="field__label">Evidence</span>
        {f.uncited ? (
          <span className="cite cite--none" title="This claim cites no evidence at all.">
            none cited
          </span>
        ) : (
          f.citations.map((c, i) => (
            <CiteChip
              key={i}
              c={c}
              open={open === i}
              onToggle={() => setOpen(open === i ? null : i)}
              id={`cite-${f.index}-${i}`}
              panelId={`cite-panel-${f.index}-${i}`}
            />
          ))
        )}
      </div>
      {shown ? (
        <div className="finding__evidence" id={`cite-panel-${f.index}-${open}`}>
          <CitationBody c={shown} />
        </div>
      ) : null}
    </li>
  );
}

function CiteChip({
  c,
  open,
  onToggle,
  id,
  panelId,
}: {
  c: NormCitation;
  open: boolean;
  onToggle: () => void;
  id: string;
  panelId: string;
}) {
  const label = c.ref === null ? fmtValue(c.raw) : `#${c.ref}`;
  const title =
    c.status === 'ok'
      ? `Evidence ${label} — ${c.entry?.tool ?? 'unknown tool'}. Click to inspect.`
      : c.status === 'failed'
        ? `Evidence ${label} is a failed tool call and cannot support a claim. Click for the error.`
        : `Evidence ${label} does not exist in this report's evidence array.`;

  return (
    <button
      type="button"
      className={open ? `cite cite--${c.status} is-open` : `cite cite--${c.status}`}
      onClick={onToggle}
      aria-expanded={open}
      aria-controls={panelId}
      id={id}
      title={title}
    >
      <span className="cite__ref mono">{label}</span>
      {c.entry?.tool ? <span className="cite__tool">{c.entry.tool}</span> : null}
      {c.status === 'failed' ? <span className="cite__flag">unusable</span> : null}
      {c.status === 'missing' ? <span className="cite__flag">no such entry</span> : null}
    </button>
  );
}

function CitationBody({ c }: { c: NormCitation }) {
  if (!c.entry) {
    return (
      <p className="state state--error">
        This claim cites evidence{' '}
        <span className="mono">{c.ref === null ? fmtValue(c.raw) : `#${c.ref}`}</span>, which is not
        in the report's evidence array. Nothing supports the claim.
      </p>
    );
  }
  return (
    <>
      {c.entry.failed ? (
        <p className="state state--error">
          The cited tool call failed, so it carries no data. A claim resting on this is unsupported.
        </p>
      ) : null}
      <EvidenceCard e={c.entry} defaultOpen />
    </>
  );
}

/* ---------- the full evidence array ---------- */

function EvidenceList({
  evidence,
  declared,
}: {
  evidence: NormEvidence[];
  declared: number | null;
}) {
  if (evidence.length === 0) {
    return (
      <div className="report__section">
        <h3 className="report__h">Evidence</h3>
        <p className="state state--empty">
          {declared && declared > 0
            ? `Verification counted ${declared} evidence entries, but none were attached to the report.`
            : 'No evidence was attached to this report.'}
        </p>
      </div>
    );
  }

  const failed = evidence.filter((e) => e.failed).length;

  return (
    <div className="report__section">
      <h3 className="report__h">
        Evidence{' '}
        <span className="dim small">
          · {evidence.length} tool call{evidence.length === 1 ? '' : 's'}
          {failed > 0 ? `, ${failed} failed` : ''}
        </span>
      </h3>
      <div className="evlist">
        {evidence.map((e) => (
          <EvidenceCard key={`${e.pos}-${e.index}`} e={e} />
        ))}
      </div>
    </div>
  );
}

/**
 * One evidence entry. Collapsed by default in the browsable list, expanded
 * when reached from a citation — payloads are arbitrary nested JSON and some
 * are large, so the body is a scroll-capped monospace block rather than
 * something that can push the page around.
 */
function EvidenceCard({ e, defaultOpen = false }: { e: NormEvidence; defaultOpen?: boolean }) {
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
        <Row label="Arguments">
          {e.hasArgs ? <Args args={e.args} /> : <span className="dim">none</span>}
        </Row>
        {e.failed ? (
          <Row label="Error">
            <p className="ev__error">{e.error}</p>
          </Row>
        ) : e.hasPayload ? (
          <Row label="Result">
            <pre className="ev__json mono">{prettyJson(e.payload)}</pre>
          </Row>
        ) : (
          <Row label="Result">
            <span className="dim">
              The entry has neither a result nor an error, so it proves nothing.
            </span>
          </Row>
        )}
      </div>
    </details>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="ev__row">
      <span className="field__label">{label}</span>
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
