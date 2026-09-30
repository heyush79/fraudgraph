/**
 * Suggested questions for the chat, derived client-side from the case's fired
 * rules (docs/showcase-contract.md §2). Replay mode does not use these: it
 * offers exactly the questions that were recorded.
 */

export const ALWAYS_ASK: readonly string[] = [
  'Why was this transaction flagged?',
  'Is this normal behaviour for this account?',
  'What evidence would change the verdict?',
];

export function suggestedQuestions(rules: readonly string[] | null | undefined): string[] {
  const r = rules ?? [];
  const out = [...ALWAYS_ASK];
  if (r.some((x) => x.startsWith('VELOCITY_'))) out.push('Could this be a genuine shopping spree?');
  if (r.includes('GEO_IMPOSSIBLE')) out.push('Could this be a real trip?');
  if (r.includes('RING_SUSPECT') || r.includes('PASS_THROUGH')) {
    out.push('Where did the money come from, and where did it go?');
  }
  if (r.includes('HARD_BLOCK_MERCHANT')) out.push('Why is this merchant blocked outright?');
  return out;
}

/** Recorded questions are matched loosely: case, spacing and a trailing "?" do not matter. */
export function sameQuestion(a: string, b: string): boolean {
  return norm(a) === norm(b);
}

function norm(s: string): string {
  return s.toLowerCase().replace(/\s+/g, ' ').replace(/[?.!\s]+$/, '').trim();
}
