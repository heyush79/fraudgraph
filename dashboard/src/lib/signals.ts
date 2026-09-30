/**
 * Vocabulary shared by every view: what a rule code, a feature name or a
 * coordinate means in words. Unknown codes fall through to a readable form of
 * the raw name, so the engine can add rules without this file changing first.
 */
import { humanKey } from './format';

/* ---------- rule codes ---------- */

const RULE_SHORT: Record<string, string> = {
  VELOCITY_1M: 'velocity 1m',
  VELOCITY_5M: 'velocity 5m',
  VELOCITY_1H: 'velocity 1h',
  GEO_IMPOSSIBLE: 'impossible travel',
  RING_SUSPECT: 'ring',
  PASS_THROUGH: 'pass-through',
  HARD_BLOCK_MERCHANT: 'sanctioned merchant',
  AMOUNT_CAP: 'amount cap',
};

/** "RING_SUSPECT" → "ring": the ticker's rule column. */
export function ruleShort(code: string): string {
  return RULE_SHORT[code] ?? code.toLowerCase().replace(/_/g, ' ');
}

/** The ticker's narrow column: one word per family, each family once. */
export function ruleFamilies(codes: readonly string[] | null | undefined): string {
  const out: string[] = [];
  for (const c of codes ?? []) {
    const w = c.startsWith('VELOCITY')
      ? 'velocity'
      : c === 'GEO_IMPOSSIBLE'
        ? 'travel'
        : c === 'RING_SUSPECT'
          ? 'ring'
          : c === 'PASS_THROUGH'
            ? 'pass-through'
            : c === 'HARD_BLOCK_MERCHANT'
              ? 'sanctioned'
              : c === 'AMOUNT_CAP'
                ? 'over cap'
                : ruleShort(c);
    if (!out.includes(w)) out.push(w);
  }
  return out.join(' + ');
}

const RULE_TITLE: Record<string, string> = {
  VELOCITY_1M: 'Payment burst, last minute',
  VELOCITY_5M: 'Payment burst, last 5 minutes',
  VELOCITY_1H: 'Payment burst, last hour',
  GEO_IMPOSSIBLE: 'Impossible travel',
  RING_SUSPECT: 'Money moving in a circle',
  PASS_THROUGH: 'Money passed straight through',
  HARD_BLOCK_MERCHANT: 'Sanctioned merchant',
  AMOUNT_CAP: 'Over the amount cap',
};

/** "RING_SUSPECT" → "Money moving in a circle": a signal card's heading. */
export function ruleTitle(code: string): string {
  return RULE_TITLE[code] ?? ruleShort(code);
}

/* ---------- case kinds, for "show me a …" ---------- */

export type CaseKind = 'RING' | 'GEO' | 'VELOCITY' | 'POLICY';
export const CASE_KINDS: readonly CaseKind[] = ['RING', 'GEO', 'VELOCITY', 'POLICY'];

export function kindsOf(rules: readonly string[] | null | undefined): CaseKind[] {
  const found = new Set<CaseKind>();
  for (const r of rules ?? []) {
    if (r === 'RING_SUSPECT' || r === 'PASS_THROUGH') found.add('RING');
    else if (r === 'GEO_IMPOSSIBLE') found.add('GEO');
    else if (r.startsWith('VELOCITY')) found.add('VELOCITY');
    else if (r === 'HARD_BLOCK_MERCHANT' || r === 'AMOUNT_CAP') found.add('POLICY');
  }
  return CASE_KINDS.filter((k) => found.has(k));
}

export function isCaseKind(s: string): s is CaseKind {
  return (CASE_KINDS as readonly string[]).includes(s);
}

/** The intro strip's buttons. POLICY depends on which hard rule fired. */
export function jumpLabel(kind: CaseKind, rules?: readonly string[] | null): string {
  switch (kind) {
    case 'RING':
      return rules && !rules.includes('RING_SUSPECT') && rules.includes('PASS_THROUGH')
        ? 'Show me money passed straight on'
        : 'Show me a laundering ring';
    case 'GEO':
      return 'Show me impossible travel';
    case 'VELOCITY':
      return 'Show me a burst of payments';
    case 'POLICY':
      return rules?.includes('AMOUNT_CAP') && !rules.includes('HARD_BLOCK_MERCHANT')
        ? 'Show me an over-the-cap payment'
        : 'Show me a sanctioned merchant';
  }
}

/* ---------- merchants ---------- */

const CATEGORY: Record<string, string> = {
  GROC: 'grocery',
  FOOD: 'food',
  FUEL: 'fuel',
  RETAIL: 'retail',
  PHARM: 'pharmacy',
  TRAVEL: 'travel',
  ELEC: 'electronics',
  GIFT: 'gift-card',
  CRYPTO: 'crypto',
  GAMBLING: 'gambling',
  P2P: 'peer-to-peer',
};

/** "CRYPTO" → "crypto"; unknown categories are lower-cased. */
export function merchantCategory(code: string | null | undefined): string | null {
  if (!code) return null;
  return CATEGORY[code] ?? code.toLowerCase();
}

/* ---------- model features ---------- */

const FEATURES: Record<string, string> = {
  cnt1m: 'Payments, last minute',
  cnt5m: 'Payments, last 5 min',
  cnt1h: 'Payments, last hour',
  sum1h: 'Amount, last hour',
  amtZ: 'Amount vs. usual (z)',
  geoSpeedKmh: 'Implied travel speed',
  secsSinceLast: 'Since previous payment',
  merchantRiskTier: 'Merchant risk tier',
  nodeDegree: 'P2P counterparties',
  inCycle: 'Closes a cycle',
  componentSize: 'Accounts in cluster',
  channel: 'Channel',
  chainDepth: 'Pass-through chain depth',
  passThroughRatio: 'Share of inbound sent on',
  secsSinceInbound: 'Since the money arrived',
};

/** Feature keys arrive as cnt1m (decision log) and cnt_1m (SHAP); both map to one label. */
export function featureKey(key: string): string {
  return key.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
}

export function featureLabel(key: string): string {
  return FEATURES[featureKey(key)] ?? humanKey(key);
}

/* ---------- places ---------- */

/**
 * The generator's home cities (generator/users.py). Its payments land within
 * about 2 km of one, so anything within 30 km is named and anything else is
 * left as coordinates rather than guessed at.
 */
const CITIES: readonly (readonly [string, number, number])[] = [
  ['Hyderabad', 17.385, 78.4867],
  ['Mumbai', 19.076, 72.8777],
  ['Delhi', 28.6139, 77.209],
  ['Bengaluru', 12.9716, 77.5946],
  ['Chennai', 13.0827, 80.2707],
  ['Kolkata', 22.5726, 88.3639],
  ['Pune', 18.5204, 73.8567],
  ['Ahmedabad', 23.0225, 72.5714],
];

export function nearestCity(lat: number | null, lon: number | null): string | null {
  if (lat === null || lon === null) return null;
  let best: string | null = null;
  let bestKm = 30;
  for (const [name, clat, clon] of CITIES) {
    const km = haversineKm(lat, lon, clat, clon);
    if (km < bestKm) {
      best = name;
      bestKm = km;
    }
  }
  return best;
}

function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLon = (lon2 - lon1) * rad;
  const a =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
}
