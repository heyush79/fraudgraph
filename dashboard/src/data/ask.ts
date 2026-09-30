import { AskError } from '../lib/api';
import { isNum } from '../lib/format';
import type {
  AnswerSentence,
  AskResponse,
  AskStep,
  EvidenceEntry,
  RemovedClaim,
  Verification,
} from '../lib/types';

/**
 * An answer crosses a network and was written by a model, so its shape is
 * checked once here rather than guarded in every component. A body that is
 * not an answer at all becomes an AskError; a body with odd parts keeps
 * whatever parts are usable.
 */
export function normalizeAsk(
  raw: unknown,
  caseId: string,
  question: string,
  mode: 'live' | 'replay',
): AskResponse {
  if (!isObj(raw) || !Array.isArray(raw.answer)) {
    throw new AskError('failed', 200, 'The analyst returned something that is not an answer.');
  }
  const answer: AnswerSentence[] = raw.answer
    .filter(isObj)
    .map((s) => ({
      text: typeof s.text === 'string' ? s.text.trim() : '',
      refs: Array.isArray(s.refs) ? s.refs.filter((r): r is number => isNum(r)) : [],
      verified: s.verified !== false,
    }))
    .filter((s) => s.text.length > 0);

  const removed: RemovedClaim[] = (Array.isArray(raw.removed) ? raw.removed : [])
    .filter(isObj)
    .map((r) => {
      const text = typeof r.text === 'string' ? r.text.trim() : '';
      const reason = typeof r.reason === 'string' ? r.reason.trim() : '';
      return { text, reason: cleanReason(reason, text) };
    })
    .filter((r) => r.text.length > 0 || r.reason.length > 0);

  const steps: AskStep[] = (Array.isArray(raw.steps) ? raw.steps : [])
    .filter(isObj)
    .map((s) => ({
      kind: (typeof s.kind === 'string' ? s.kind : 'tool') as AskStep['kind'],
      label: typeof s.label === 'string' ? s.label : '',
      ...(typeof s.detail === 'string' && s.detail ? { detail: s.detail } : {}),
      ...(isNum(s.ms) ? { ms: s.ms } : {}),
    }))
    .filter((s) => s.label.length > 0);

  return {
    caseId: typeof raw.caseId === 'string' ? raw.caseId : caseId,
    question: typeof raw.question === 'string' && raw.question.trim() ? raw.question : question,
    answer,
    removed,
    evidence: (Array.isArray(raw.evidence) ? raw.evidence : []) as EvidenceEntry[],
    steps,
    verification: (isObj(raw.verification) ? raw.verification : {}) as Verification,
    model: typeof raw.model === 'string' ? raw.model : '',
    latencyMs: isNum(raw.latencyMs) ? raw.latencyMs : 0,
    mode: raw.mode === 'live' || raw.mode === 'replay' ? raw.mode : mode,
    ...(raw.cached === true ? { cached: true } : {}),
    ...(typeof raw.note === 'string' && raw.note ? { note: raw.note } : {}),
  };
}

/**
 * The verifier's detail ends by quoting the claim ("…in evidence [2]: 'This
 * account has…'"). The UI shows the claim right above the reason, so the
 * repeat is dropped.
 */
export function cleanReason(reason: string, claim: string): string {
  if (!claim) return reason;
  for (const q of ["'", '"']) {
    const tail = `: ${q}${claim}${q}`;
    if (reason.endsWith(tail)) return reason.slice(0, -tail.length);
  }
  return reason;
}

function isObj(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}
