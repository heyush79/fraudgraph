/** Formatting helpers. Everything here must survive null/undefined/NaN input. */
import { IS_REPLAY } from '../config';

const TIME = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const DATETIME = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'medium',
});

const DATE_UTC = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'UTC',
});

// The generator's amounts are rupees (README: "₹20k–80k P2P").
const MONEY = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
});

const MONEY0 = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
});

export const DASH = '—';

/** 16:02:11 — the ticker's column. */
export function fmtClock(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? TIME.format(d) : DASH;
}

/** 16:02:11.123 — for tooltips, where the milliseconds are the point. */
export function fmtClockMs(iso: string | null | undefined): string {
  const d = toDate(iso);
  if (!d) return DASH;
  return `${TIME.format(d)}.${String(d.getMilliseconds()).padStart(3, '0')}`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? DATETIME.format(d) : DASH;
}

/** "29 Sep 2026, 16:02 UTC" — the one place a recording's date is shown. */
export function fmtDateUtc(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? `${DATE_UTC.format(d)} UTC` : DASH;
}

export function fmtAgo(iso: string | null | undefined, now = Date.now()): string {
  const d = toDate(iso);
  if (!d) return DASH;
  const secs = Math.max(0, Math.round((now - d.getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

/**
 * When something happened, as a reader of this deployment needs it. Live mode
 * says "12s ago". A replay says the recorded clock time instead, because "15d
 * ago" measured from today describes the recording's age, not the event.
 */
export function fmtWhen(iso: string | null | undefined): string {
  return IS_REPLAY ? fmtClock(iso) : fmtAgo(iso);
}

/**
 * Durations as an analyst would say them: a 60-second velocity window is "60s",
 * not "1m 0s"; 300 is "5m"; a 7-minute geo gap is "7m", not "7m 0s".
 */
export function fmtSecs(secs: number | null | undefined): string {
  if (!isNum(secs)) return DASH;
  if (secs < 0) return DASH;
  if (secs < 90) return `${round(secs, secs < 10 ? 1 : 0)}s`;
  const m = Math.floor(secs / 60);
  const s = Math.round(secs % 60);
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
}

const SMALL = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];

/** Durations in words, for sentences: 184 → "three minutes", 45 → "45 seconds". */
export function humanSecs(secs: number | null | undefined): string {
  if (!isNum(secs) || secs < 0) return DASH;
  if (secs < 1) return 'under a second';
  if (secs < 90) {
    const n = Math.round(secs);
    return `${n} second${n === 1 ? '' : 's'}`;
  }
  if (secs < 5400) {
    const m = Math.round(secs / 60);
    return `${spell(m)} minute${m === 1 ? '' : 's'}`;
  }
  const h = Math.round(secs / 3600);
  return `${spell(h)} hour${h === 1 ? '' : 's'}`;
}

/** A window length as a phrase: 60 → "60 seconds", 300 → "5 minutes", 3600 → "1 hour". */
export function windowPhrase(secs: number | null | undefined): string {
  if (!isNum(secs) || secs <= 0) return 'the window';
  if (secs % 3600 === 0) return `${secs / 3600} hour${secs === 3600 ? '' : 's'}`;
  if (secs % 60 === 0 && secs >= 120) return `${secs / 60} minutes`;
  return `${fmtNum(secs, 0)} seconds`;
}

function spell(n: number): string {
  return n >= 0 && n < SMALL.length ? SMALL[n] : String(n);
}

export function fmtNum(n: unknown, digits = 2): string {
  if (!isNum(n)) return DASH;
  return n.toLocaleString(undefined, {
    minimumFractionDigits: Number.isInteger(n) ? 0 : digits,
    maximumFractionDigits: digits,
  });
}

export function fmtInt(n: unknown): string {
  return isNum(n) ? Math.round(n).toLocaleString(undefined) : DASH;
}

export function fmtMoney(n: unknown): string {
  return isNum(n) ? MONEY.format(n) : DASH;
}

/** Whole rupees, for sentences: ₹41,230. */
export function fmtMoney0(n: unknown): string {
  return isNum(n) ? MONEY0.format(n) : DASH;
}

export function fmtScore(n: number | null | undefined): string {
  return isNum(n) ? n.toFixed(4) : DASH;
}

/** 14 → "14 ms", 2140 → "2.1 s". */
export function fmtMs(ms: number | null | undefined): string {
  if (!isNum(ms) || ms < 0) return DASH;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

/** 0.961 → "96%". */
export function fmtPct(ratio: number | null | undefined, digits = 0): string {
  return isNum(ratio) ? `${(ratio * 100).toFixed(digits)}%` : DASH;
}

/** Feature/SHAP keys arrive in two casings (cnt1m vs cnt_1m); show one. */
export function humanKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/([a-z])([A-Z0-9])/g, '$1 $2').toLowerCase();
}

export function titleCase(s: string): string {
  return s
    .toLowerCase()
    .split(/[\s_]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ');
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : DASH;
}

export function isNum(n: unknown): n is number {
  return typeof n === 'number' && Number.isFinite(n);
}

export function round(n: number, digits: number): number {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}

/** Cheap, deterministic stringify for unknown evidence payloads. */
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return DASH;
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return fmtNum(v, 3);
  if (Array.isArray(v)) return v.map(fmtValue).join(' → ');
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/**
 * Epoch ms of an ISO timestamp. The engine writes nanosecond fractions
 * ("…57.723671131Z"); trimmed to milliseconds so every engine parses them.
 */
export function parseTime(iso: string | null | undefined): number {
  if (!iso) return Number.NaN;
  return Date.parse(iso.replace(/(\.\d{3})\d+/, '$1'));
}

function toDate(iso: string | null | undefined): Date | null {
  const t = parseTime(iso);
  return Number.isNaN(t) ? null : new Date(t);
}
