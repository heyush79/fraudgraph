/** Formatting helpers. Everything here must survive null/undefined/NaN input. */

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

// The generator's amounts are rupees (README: "₹20k–80k P2P").
const MONEY = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
});

export const DASH = '—';

export function fmtClock(iso: string | null | undefined): string {
  const d = toDate(iso);
  if (!d) return DASH;
  const ms = String(d.getMilliseconds()).padStart(3, '0');
  return `${TIME.format(d)}.${ms}`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? DATETIME.format(d) : DASH;
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

export function fmtNum(n: unknown, digits = 2): string {
  if (!isNum(n)) return DASH;
  return n.toLocaleString(undefined, {
    minimumFractionDigits: Number.isInteger(n) ? 0 : digits,
    maximumFractionDigits: digits,
  });
}

export function fmtMoney(n: unknown): string {
  return isNum(n) ? MONEY.format(n) : DASH;
}

export function fmtScore(n: number | null | undefined): string {
  return isNum(n) ? n.toFixed(4) : DASH;
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

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}
