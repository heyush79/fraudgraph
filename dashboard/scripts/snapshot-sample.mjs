#!/usr/bin/env node
/**
 * Writes a SMALL development sample in the replay format
 * (docs/showcase-contract.md §3) into dashboard/public/showcase/, read from a
 * running stack, so the replay build can be worked on before a real recording
 * exists. The real recorder overwrites the same directory.
 *
 *   node scripts/snapshot-sample.mjs [--seconds 60] [--api http://localhost:8082]
 *                                    [--agent http://localhost:8010] [--scorer http://localhost:8000]
 *
 * Read-only against the stack: HTTP GETs and one WebSocket subscription. It
 * never PATCHes, never POSTs.
 *
 * What is in it, and how honest each part is:
 *   feed.json        the live decision stream, recorded for --seconds (real, real timing)
 *   cases/*.json     up to six real cases: featured ones picked from REPORTED cases
 *                    whose analyst report passed verification, one fresh ring or
 *                    pass-through case with a live graph, and the newest flagged cases
 *                    seen in the recorded feed
 *   history, graph   the live /internal reads for each case's account; where the live
 *                    state has aged out (the graph keeps 24 h), the payload the agent
 *                    recorded for that account at investigation time
 *   ask/*.json       NOT real answers: src/data/askFixture.js templates filled with each
 *                    case's numbers, and labelled "sample fixture" in `model`
 *   manifest.json    "sample": true
 *
 * Plain Node 22+ (global fetch and WebSocket), no dependencies.
 */
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildFixtureAnswer } from '../src/data/askFixture.js';

const args = parseArgs(process.argv.slice(2));
const API = (args.api ?? 'http://localhost:8082').replace(/\/+$/, '');
const AGENT = (args.agent ?? 'http://localhost:8010').replace(/\/+$/, '');
const SCORER = (args.scorer ?? 'http://localhost:8000').replace(/\/+$/, '');
const SECONDS = Number(args.seconds ?? 60);
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'showcase');
const MAX_CASES = 6;

const ALWAYS = ['Why was this transaction flagged?', 'Is this normal behaviour for this account?'];
const BY_RULE = [
  [(r) => r.some((x) => x.startsWith('VELOCITY_')), 'Could this be a genuine shopping spree?'],
  [(r) => r.includes('GEO_IMPOSSIBLE'), 'Could this be a real trip?'],
  [(r) => r.includes('RING_SUSPECT') || r.includes('PASS_THROUGH'), 'Where did the money come from, and where did it go?'],
  [(r) => r.includes('HARD_BLOCK_MERCHANT'), 'Why is this merchant blocked outright?'],
];

main().catch((err) => {
  console.error(`snapshot failed: ${err instanceof Error ? err.message : err}`);
  process.exit(1);
});

async function main() {
  if (typeof WebSocket === 'undefined' || typeof fetch === 'undefined') {
    throw new Error('needs Node 22 or newer (global fetch and WebSocket)');
  }
  await get(`${API}/stats`); // fail fast if the case service is not up

  console.log(`recording ${SECONDS}s of ${API.replace(/^http/, 'ws')}/ws/feed …`);
  const feed = await recordFeed(SECONDS);
  console.log(`  ${feed.ticks.length} decisions, ${feed.ticks.filter((t) => t.verdict !== 'ALLOW').length} flagged`);

  // Featured: one per pattern, from reported cases whose report passed the verifier.
  const reported = (await get(`${API}/cases?status=REPORTED&limit=200&offset=0`)).items ?? [];
  const chosen = new Map(); // caseId -> { detail, featured: pattern | null }
  for (const pattern of ['RING', 'GEO', 'VELOCITY', 'POLICY']) {
    for (const summary of reported) {
      if (kindOf(summary.firedRules) !== pattern || chosen.has(summary.caseId)) continue;
      const detail = await get(`${API}/cases/${summary.caseId}`);
      const v = detail.reportDoc?.verification;
      if (v?.passed === true && (detail.reportDoc?.findings?.length ?? 0) > 0) {
        chosen.set(summary.caseId, { detail, featured: pattern === 'POLICY' ? null : pattern });
        break;
      }
    }
  }
  // One fresh money-movement case whose account still has transfers in the
  // engine's graph (it keeps 24 h), so the sample has a network to draw.
  const recent = (await get(`${API}/cases?limit=200&offset=0`)).items ?? [];
  for (const summary of recent) {
    if (kindOf(summary.firedRules) !== 'RING' || chosen.has(summary.caseId)) continue;
    const nb = await get(`${API}/internal/graph/${encodeURIComponent(summary.userId)}/neighborhood?depth=2`).catch(() => null);
    if ((nb?.edges?.length ?? 0) > 0) {
      chosen.set(summary.caseId, { detail: await get(`${API}/cases/${summary.caseId}`), featured: null });
      break;
    }
  }

  // Plus the newest flagged cases from the recording itself, so some ticker rows open.
  const flagged = feed.ticks.filter((t) => t.caseId && t.verdict !== 'ALLOW').reverse();
  for (const t of flagged) {
    if (chosen.size >= MAX_CASES) break;
    if (chosen.has(t.caseId)) continue;
    try {
      chosen.set(t.caseId, { detail: await get(`${API}/cases/${t.caseId}`), featured: null });
    } catch (err) {
      console.warn(`  skipped ${t.caseId}: ${err.message}`);
    }
  }
  if (chosen.size === 0) throw new Error('no cases to sample: nothing reported, nothing flagged');

  await rm(OUT, { recursive: true, force: true });
  for (const dir of ['cases', 'history', 'graph', 'ask']) await mkdir(join(OUT, dir), { recursive: true });

  const featured = [];
  for (const [caseId, { detail, featured: pattern }] of chosen) {
    const userId = detail.userId;
    const history = await accountHistory(detail);
    const graph = await accountGraph(detail);
    await write(`cases/${caseId}.json`, detail);
    if (history) await write(`history/${userId}.json`, history);
    if (graph) await write(`graph/${userId}.json`, graph);

    const rules = detail.firedRules ?? detail.decisionDoc?.firedRules ?? [];
    const questions = [ALWAYS[0], ...BY_RULE.filter(([test]) => test(rules)).map(([, q]) => q), ALWAYS[1]];
    const answers = questions.map((question) =>
      buildFixtureAnswer({ detail, history, graph, question, mode: 'replay', model: 'sample fixture (no model called)' }),
    );
    await write(`ask/${caseId}.json`, { answers });

    if (pattern) featured.push({ caseId, pattern, ...describe(pattern, detail) });
    console.log(`  case ${caseId.slice(0, 8)} ${detail.verdict} ${rules.join(',') || '(model only)'}${pattern ? `  featured ${pattern}` : ''}`);
  }

  const items = [...chosen.values()]
    .map(({ detail: d }) => ({
      caseId: d.caseId,
      txnId: d.txnId,
      userId: d.userId,
      verdict: d.verdict,
      mlScore: d.mlScore,
      status: d.status,
      firedRules: d.firedRules,
      createdAt: d.createdAt,
      updatedAt: d.updatedAt,
    }))
    .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
  await write('cases.json', { items, total: items.length });
  await write('feed.json', { ticks: feed.ticks });

  const byStatus = {};
  for (const c of items) byStatus[c.status] = (byStatus[c.status] ?? 0) + 1;
  const agent = await get(`${AGENT}/health`).catch(() => null);
  const scorer = await get(`${SCORER}/health`).catch(() => null);
  const durationMs = Math.max(SECONDS * 1000, (feed.ticks.at(-1)?.at ?? 0) + 200);
  await write('manifest.json', {
    recordedAt: feed.startedAt,
    durationMs,
    tps: Math.round((feed.ticks.length / (durationMs / 1000)) * 10) / 10,
    scorerModel: scorer?.modelVersion ?? 'unknown',
    agentModel: agent?.model ? `${agent.model}${agent.provider ? ` via ${titleCase(agent.provider)}` : ''}` : 'unknown',
    stats: {
      byStatus,
      total: items.length,
      last1h: {
        cases: items.length,
        review: items.filter((c) => c.verdict === 'REVIEW').length,
        block: items.filter((c) => c.verdict === 'BLOCK').length,
      },
    },
    featured,
    sample: true,
  });
  console.log(`wrote ${chosen.size} cases, ${featured.length} featured, into ${OUT}`);
}

/* ---------- the feed ---------- */

function recordFeed(seconds) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`${API.replace(/^http/, 'ws')}/ws/feed`);
    const ticks = new Map();
    let first = true;
    let startedAt = null;
    const timer = setTimeout(() => ws.close(1000, 'done'), seconds * 1000);
    ws.onopen = () => {
      startedAt = new Date().toISOString();
    };
    ws.onmessage = (ev) => {
      // The first frame is the server's 200-tick backfill, from before the recording.
      if (first) {
        first = false;
        return;
      }
      let batch;
      try {
        batch = JSON.parse(String(ev.data));
      } catch {
        return;
      }
      const arrived = Date.now();
      for (const t of Array.isArray(batch) ? batch : [batch]) {
        if (t && typeof t.txnId === 'string' && !ticks.has(t.txnId)) ticks.set(t.txnId, { tick: t, arrived });
      }
    };
    ws.onerror = () => {
      clearTimeout(timer);
      reject(new Error(`cannot open ${API.replace(/^http/, 'ws')}/ws/feed`));
    };
    ws.onclose = () => {
      clearTimeout(timer);
      // A tick normally arrives within a second of its decision. The server can
      // also re-send older ticks (the tail of its backfill arriving as a second
      // frame was seen); those would stretch the timeline with a dead gap, so any
      // tick that arrived more than 5 s later than is typical is dropped.
      const all = [...ticks.values()].filter(({ tick }) => Number.isFinite(parseTime(tick.decidedAt)));
      const lags = all.map(({ tick, arrived }) => arrived - parseTime(tick.decidedAt)).sort((a, b) => a - b);
      const typical = lags[Math.floor(lags.length / 2)] ?? 0;
      const list = all
        .filter(({ tick, arrived }) => arrived - parseTime(tick.decidedAt) - typical <= 5_000)
        .map(({ tick }) => tick);
      if (list.length < all.length) console.log(`  dropped ${all.length - list.length} late re-sent ticks`);
      const t0 = Math.min(...list.map((t) => parseTime(t.decidedAt)));
      // `at` is the recorded offset of each decision; replay plays them back at it.
      const out = list
        .map((t) => ({ ...t, at: Math.max(0, Math.round(parseTime(t.decidedAt) - t0)) }))
        .sort((a, b) => a.at - b.at);
      resolve({ ticks: out, startedAt: startedAt ?? new Date(t0).toISOString() });
    };
  });
}

/* ---------- per-account reads ---------- */

async function accountHistory(detail) {
  const live = await get(`${API}/internal/users/${encodeURIComponent(detail.userId)}/history?hours=24`).catch(() => null);
  const complete = (h) => h && (h.profile || h.windows) && (h.recent?.length ?? 0) > 0;
  if (complete(live)) return live;
  // The live list keeps 24 h and the engine's state can be unreachable; for an
  // older case, what the agent read at the time is the better record.
  const recorded = reportPayload(detail, 'get_user_history');
  if (complete(recorded)) return recorded;
  return live ?? recorded;
}

async function accountGraph(detail) {
  const live = await get(`${API}/internal/graph/${encodeURIComponent(detail.userId)}/neighborhood?depth=2`).catch(() => null);
  if (live && (live.edges?.length ?? 0) > 0) return live;
  const recorded = reportPayload(detail, 'get_graph_neighborhood');
  return recorded && (recorded.edges?.length ?? 0) > 0 ? recorded : live;
}

function reportPayload(detail, tool) {
  const entry = (detail.reportDoc?.evidence ?? []).find((e) => e.tool === tool && e.payload && !e.error);
  return entry ? entry.payload : null;
}

/* ---------- featured copy, from the case's own evidence ---------- */

function describe(pattern, detail) {
  const signals = detail.decisionDoc?.signals ?? [];
  const sig = (code) => signals.find((s) => s.code === code || (code === 'VELOCITY' && s.code.startsWith('VELOCITY')))?.evidence ?? {};
  const blocked = detail.verdict === 'BLOCK' ? 'was blocked' : 'was sent for review';
  if (pattern === 'RING') {
    const cycle = sig('RING_SUSPECT').cycle ?? [];
    const n = Math.max(0, cycle.length - 1);
    return {
      title: `A ${spell(n)}-account laundering ring`,
      blurb: `Money went ${cycle.join(' → ')}. The payment that closed the loop ${blocked}.`,
    };
  }
  if (pattern === 'GEO') {
    const e = sig('GEO_IMPOSSIBLE');
    const from = nearestCity(e.fromLat, e.fromLon) ?? 'One city';
    const to = nearestCity(e.toLat, e.toLon) ?? 'another';
    return {
      title: `${from}, then ${to}, ${minutes(e.gapSecs)} later`,
      blurb: `${Math.round(e.distanceKm).toLocaleString('en-US')} km apart: an implied ${Math.round(e.speedKmh).toLocaleString('en-US')} km/h, where the engine's ceiling is ${e.maxSpeedKmh} km/h.`,
    };
  }
  const e = sig('VELOCITY');
  return {
    title: `${e.count} payments in ${e.windowSecs === 60 ? 'a minute' : `${e.windowSecs} seconds`}`,
    blurb: `The limit is ${e.limit}. ₹${Math.round(e.sum ?? 0).toLocaleString('en-IN')} moved inside that window.`,
  };
}

function kindOf(rules = []) {
  if (rules.includes('RING_SUSPECT') || rules.includes('PASS_THROUGH')) return 'RING';
  if (rules.includes('GEO_IMPOSSIBLE')) return 'GEO';
  if (rules.some((r) => r.startsWith('VELOCITY'))) return 'VELOCITY';
  if (rules.includes('HARD_BLOCK_MERCHANT') || rules.includes('AMOUNT_CAP')) return 'POLICY';
  return null;
}

// generator/users.py; payments land within ~2 km of one of these.
const CITIES = [
  ['Hyderabad', 17.385, 78.4867], ['Mumbai', 19.076, 72.8777], ['Delhi', 28.6139, 77.209],
  ['Bengaluru', 12.9716, 77.5946], ['Chennai', 13.0827, 80.2707], ['Kolkata', 22.5726, 88.3639],
  ['Pune', 18.5204, 73.8567], ['Ahmedabad', 23.0225, 72.5714],
];

function nearestCity(lat, lon) {
  if (typeof lat !== 'number' || typeof lon !== 'number') return null;
  let best = null;
  let bestKm = 30;
  for (const [name, clat, clon] of CITIES) {
    const r = Math.PI / 180;
    const a = Math.sin(((clat - lat) * r) / 2) ** 2 + Math.cos(lat * r) * Math.cos(clat * r) * Math.sin(((clon - lon) * r) / 2) ** 2;
    const km = 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
    if (km < bestKm) [best, bestKm] = [name, km];
  }
  return best;
}

function minutes(secs) {
  const m = Math.round((secs ?? 0) / 60);
  return m <= 1 ? 'a minute' : `${spell(m)} minutes`;
}

function spell(n) {
  return ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'][n] ?? String(n);
}

function titleCase(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/* ---------- plumbing ---------- */

async function get(url) {
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`${res.status} from ${url}`);
  return res.json();
}

async function write(path, value) {
  await writeFile(join(OUT, path), `${JSON.stringify(value)}\n`);
}

function parseTime(iso) {
  return typeof iso === 'string' ? Date.parse(iso.replace(/(\.\d{3})\d+/, '$1')) : Number.NaN;
}

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const m = /^--([a-z]+)(?:=(.*))?$/.exec(argv[i]);
    if (!m) continue;
    out[m[1]] = m[2] ?? argv[i + 1];
    if (m[2] === undefined) i += 1;
  }
  return out;
}
