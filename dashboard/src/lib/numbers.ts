/**
 * The verifier's number check, mirrored for display only. The agent's verify
 * node (analyst-agent/agent/verify.py) decides what is supported; this file
 * only finds the numbers a sentence quotes so the UI can highlight where each
 * one appears in the evidence the sentence cites. Keep the regexes and the
 * tolerance in step with verify.py.
 */

// 1,234.56 | 1234 | 0.91 | -3.8 — grouped thousands, or none.
const NUMBER = /-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?/g;
// Numbers inside an ISO timestamp say when, not how many.
const ISO_TIMESTAMP = /\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z?/g;
// verify.py MIN_CHECKED_VALUE: small integers are ordinary English and are not policed.
const MIN_CHECKED = 3;
// verify.py REL_TOLERANCE: "13,500" for 13499.3 is rounding, not a wrong number.
const REL_TOLERANCE = 0.01;

export interface Quantity {
  value: number;
  percent: boolean;
}

/** The quantities a sentence asserts, the way verify.py extracts them. */
export function quantities(text: string): Quantity[] {
  const cleaned = text.replace(ISO_TIMESTAMP, ' ');
  const out: Quantity[] = [];
  for (const m of cleaned.matchAll(NUMBER)) {
    const value = Number(m[0].replace(/,/g, ''));
    if (!Number.isFinite(value) || Math.abs(value) < MIN_CHECKED) continue;
    const end = (m.index ?? 0) + m[0].length;
    out.push({ value, percent: cleaned[end] === '%' });
  }
  return out;
}

/** Does a number found in the evidence support one of the quoted quantities? */
export function supports(evidenceValue: number, quoted: readonly Quantity[]): boolean {
  return quoted.some(
    (q) => close(q.value, evidenceValue) || (q.percent && close(q.value / 100, evidenceValue)),
  );
}

function close(a: number, b: number): boolean {
  if (a === b) return true;
  if (Math.abs(a - b) <= Math.max(Math.abs(a), Math.abs(b)) * REL_TOLERANCE) return true;
  return Math.round(a) === Math.round(b);
}

/** Splits text into plain runs and number tokens, for highlighting inside JSON. */
export function splitNumbers(text: string): { text: string; value: number | null }[] {
  const out: { text: string; value: number | null }[] = [];
  let last = 0;
  for (const m of text.matchAll(/-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g)) {
    const start = m.index ?? 0;
    if (start > last) out.push({ text: text.slice(last, start), value: null });
    out.push({ text: m[0], value: Number(m[0]) });
    last = start + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), value: null });
  return out;
}
