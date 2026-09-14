/**
 * Normalises the analyst agent's report before any of it is rendered.
 *
 * The report is written by an LLM and travels through the agent and the case
 * service before it reaches here, so nothing in it can be trusted to have the
 * declared type: `findings` may be absent, `evidence_refs` may be a string, an
 * evidence entry may have neither `payload` nor `error`. Every widening of the
 * contract is absorbed in this file so the components below it can be written
 * against total, plain shapes and never guard again.
 *
 * Nothing here throws, and nothing is dropped silently that a reader would
 * want to see: malformed citations survive as `missing` citations, unexpected
 * enum values survive as their raw string.
 */
import { isNum } from './format';
import type { ReportDoc, ViolationKind } from './types';

export const FRAUD_TYPES = ['RING', 'VELOCITY', 'GEO', 'MIXED', 'UNCERTAIN'] as const;
export const ACTIONS = ['CONFIRM_BLOCK', 'RELEASE', 'ESCALATE'] as const;

/** One entry of `evidence[]`: exactly one tool call, and its result or its failure. */
export interface NormEvidence {
  /** `index` as declared by the agent, falling back to array position. */
  index: number;
  /** Array position — stable even when two entries claim the same `index`. */
  pos: number;
  tool: string | null;
  args: unknown;
  hasArgs: boolean;
  payload: unknown;
  hasPayload: boolean;
  error: string | null;
  /** True when the tool call failed, so this entry carries no citable data. */
  failed: boolean;
}

/** `ok` — resolvable and usable. `failed` — resolves to a failed tool call. `missing` — no such index. */
export type CitationStatus = 'ok' | 'failed' | 'missing';

export interface NormCitation {
  ref: number | null;
  /** The raw value when it was not even a number, e.g. `"0"` or `null`. */
  raw: unknown;
  entry: NormEvidence | null;
  status: CitationStatus;
}

export interface NormFinding {
  /** Position in `findings[]` — what `violation.finding_index` refers to. */
  index: number;
  claim: string | null;
  citations: NormCitation[];
  /** True when `evidence_refs` was absent, empty or not an array at all. */
  uncited: boolean;
}

export interface NormViolation {
  /** null when the agent sent -1, i.e. not tied to one claim. */
  findingIndex: number | null;
  kind: string | null;
  detail: string | null;
  /**
   * The claim this violation was raised against, when it is still in the
   * report. Violations are the union across attempts and an escalated report
   * has its unsupported findings stripped, so this is often null even for a
   * violation with a real finding index.
   */
  claim: string | null;
}

export interface NormVerification {
  /** null when the field was absent or not a boolean — "unknown", not "failed". */
  passed: boolean | null;
  attempts: number | null;
  toolCallsUsed: number | null;
  evidenceCount: number | null;
  violations: NormViolation[];
}

export interface NormReport {
  summary: string | null;
  fraudType: string | null;
  confidence: number | null;
  action: string | null;
  findings: NormFinding[];
  evidence: NormEvidence[];
  verification: NormVerification | null;
  /** True when there is nothing worth rendering at all. */
  empty: boolean;
}

export const VIOLATION_LABELS: Record<ViolationKind, string> = {
  no_refs: 'Claim cited nothing',
  bad_ref: 'Citation points nowhere',
  uncited_number: 'Number not in the cited evidence',
  failed_tool_ref: 'Citation points at a failed tool call',
};

export const VIOLATION_HELP: Record<ViolationKind, string> = {
  no_refs: 'The claim carried no evidence_refs at all, so nothing supports it.',
  bad_ref: 'An evidence_refs index does not exist in the evidence array.',
  uncited_number:
    'A number quoted in the claim does not appear anywhere in the evidence the claim cites.',
  failed_tool_ref:
    'The cited tool call returned an error, so it carries no data that could support a claim.',
};

export function violationLabel(kind: string | null): string {
  if (!kind) return 'Unspecified failure';
  return VIOLATION_LABELS[kind as ViolationKind] ?? kind;
}

export function violationHelp(kind: string | null): string | null {
  if (!kind) return null;
  return VIOLATION_HELP[kind as ViolationKind] ?? null;
}

function str(v: unknown): string | null {
  if (typeof v === 'string') {
    const t = v.trim();
    return t.length > 0 ? t : null;
  }
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return null;
}

function int(v: unknown): number | null {
  if (isNum(v)) return Math.trunc(v);
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    if (Number.isFinite(n)) return Math.trunc(n);
  }
  return null;
}

function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function obj(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function normEvidence(raw: unknown, pos: number): NormEvidence {
  const e = obj(raw);
  const declared = int(e.index);
  const error = str(e.error);
  // `payload` is an arbitrary JSON value, so `null` and `false` are real
  // payloads: presence is decided by the key, not by truthiness.
  const hasPayload = 'payload' in e && e.payload !== undefined;
  return {
    index: declared ?? pos,
    pos,
    tool: str(e.tool),
    args: e.args,
    hasArgs: e.args !== undefined && e.args !== null,
    payload: e.payload,
    hasPayload,
    error,
    failed: error !== null,
  };
}

/**
 * Citations resolve through the `index` the agent declared, not the array
 * position, because that is what `evidence_refs` means. First entry wins if
 * two claim the same index — arbitrary, but stable and never a crash.
 */
function buildIndex(evidence: NormEvidence[]): Map<number, NormEvidence> {
  const map = new Map<number, NormEvidence>();
  for (const e of evidence) if (!map.has(e.index)) map.set(e.index, e);
  return map;
}

function normCitation(raw: unknown, byIndex: Map<number, NormEvidence>): NormCitation {
  const ref = int(raw);
  if (ref === null) return { ref: null, raw, entry: null, status: 'missing' };
  const entry = byIndex.get(ref) ?? null;
  if (!entry) return { ref, raw, entry: null, status: 'missing' };
  return { ref, raw, entry, status: entry.failed ? 'failed' : 'ok' };
}

function normFinding(raw: unknown, index: number, byIndex: Map<number, NormEvidence>): NormFinding {
  const f = obj(raw);
  const refs = arr(f.evidence_refs);
  return {
    index,
    claim: str(f.claim),
    citations: refs.map((r) => normCitation(r, byIndex)),
    uncited: refs.length === 0,
  };
}

function normVerification(raw: unknown, findings: NormFinding[]): NormVerification | null {
  if (raw === null || raw === undefined) return null;
  const v = obj(raw);
  if (Object.keys(v).length === 0) return null;
  const violations = arr(v.violations).map((rv) => {
    const o = obj(rv);
    const fi = int(o.finding_index);
    // -1 means "not tied to a specific finding". So does any index outside the
    // surviving findings array, which happens whenever a report was escalated
    // and its unsupported findings stripped.
    const findingIndex = fi !== null && fi >= 0 ? fi : null;
    return {
      findingIndex,
      kind: str(o.kind),
      detail: str(o.detail),
      claim: findingIndex !== null ? (findings[findingIndex]?.claim ?? null) : null,
    };
  });
  return {
    passed: typeof v.passed === 'boolean' ? v.passed : null,
    attempts: int(v.attempts),
    toolCallsUsed: int(v.toolCallsUsed),
    evidenceCount: int(v.evidenceCount),
    violations,
  };
}

export function normalizeReport(raw: ReportDoc | null | undefined): NormReport | null {
  if (raw === null || raw === undefined || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;

  const evidence = arr(r.evidence).map(normEvidence);
  const byIndex = buildIndex(evidence);
  const findings = arr(r.findings).map((f, i) => normFinding(f, i, byIndex));
  const verification = normVerification(r.verification, findings);

  const confidenceRaw = r.confidence;
  const confidence = isNum(confidenceRaw) ? Math.min(1, Math.max(0, confidenceRaw)) : null;

  const summary = str(r.summary);
  const fraudType = str(r.fraud_type);
  const action = str(r.recommended_action);

  return {
    summary,
    fraudType,
    confidence,
    action,
    findings,
    evidence,
    verification,
    empty:
      summary === null &&
      fraudType === null &&
      action === null &&
      confidence === null &&
      findings.length === 0 &&
      evidence.length === 0 &&
      verification === null,
  };
}

/** Pretty-printed JSON for the evidence blocks. Never throws, never returns ''. */
export function prettyJson(v: unknown): string {
  if (v === undefined) return 'undefined';
  try {
    const out = JSON.stringify(v, null, 2);
    return out === undefined ? String(v) : out;
  } catch {
    // Circular or non-serialisable — should not happen over JSON, but the
    // evidence payload is arbitrary and this must not take the page down.
    return String(v);
  }
}

/** A one-line shape hint for a collapsed payload, so the reader knows what is inside. */
export function shapeHint(v: unknown): string {
  if (v === null) return 'null';
  if (v === undefined) return 'no payload';
  if (Array.isArray(v)) return `array · ${v.length} item${v.length === 1 ? '' : 's'}`;
  if (typeof v === 'object') {
    const keys = Object.keys(v as object);
    if (keys.length === 0) return 'object · empty';
    const head = keys.slice(0, 4).join(', ');
    return `object · ${head}${keys.length > 4 ? `, +${keys.length - 4}` : ''}`;
  }
  if (typeof v === 'string') return `string · ${v.length} char${v.length === 1 ? '' : 's'}`;
  return typeof v;
}
