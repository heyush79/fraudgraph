// @ts-check
/**
 * A realistic AskResponse built from a real case, for two jobs:
 *   - the dev-only chat fixture (`?fixture`, see src/config.ts), so the chat
 *     panel can be built and screenshotted without calling a model;
 *   - the ask files of the development sample (scripts/snapshot-sample.mjs).
 *
 * It is not the analyst. Every sentence is a template filled in with the case's
 * own numbers, every number it quotes is present in the evidence it cites (so
 * it would pass the real verifier), and exactly one extra claim is "removed"
 * the way the verifier removes one, so the disclosure can be seen. `model`
 * always says it is a fixture. The evidence and steps follow the shapes
 * agent/ask.py sends (docs/showcase-contract.md §2).
 *
 * Plain JavaScript on purpose: the snapshot script imports it with no build
 * step. Types are in askFixture.d.ts.
 */

/**
 * @param {{ detail: any, history?: any, graph?: any, question: string, mode?: 'live' | 'replay', model?: string }} input
 * @returns {any} an AskResponse
 */
export function buildFixtureAnswer({ detail, history = null, graph = null, question, mode = 'live', model = 'fixture (no model called)' }) {
  const d = detail.decisionDoc || {};
  const userId = d.userId || detail.userId;
  const signals = Array.isArray(d.signals) ? d.signals : [];
  const byCode = (/** @type {string} */ code) => signals.find((s) => s && s.code === code);
  const velocity = signals.find((s) => s && typeof s.code === 'string' && s.code.startsWith('VELOCITY'));
  const kind = questionKind(question);

  /** @type {any[]} */
  const evidence = [{ index: 0, tool: 'decision', args: { txnId: d.txnId || detail.txnId }, payload: d }];
  /** @type {any[]} */
  const steps = [{ kind: 'evidence', label: 'Loaded the decision and its signals', ms: 9 }];
  const addTool = (/** @type {string} */ tool, /** @type {any} */ args, /** @type {any} */ payload, /** @type {string | null} */ error, /** @type {number} */ ms) => {
    evidence.push({ index: evidence.length, tool, args, ...(error ? { error } : { payload }) });
    const argText = Object.entries(args).map(([k, v]) => `${k}=${v}`).join(', ');
    steps.push({ kind: 'tool', label: `${tool}(${argText})`, ms, ...(error ? { detail: error } : {}) });
    return evidence.length - 1;
  };

  // The server pre-fetches history for "normal / usual / genuine" questions and
  // the graph for money-flow questions, before the model is called.
  const view = historyView(userId, history);
  const historyRef = addTool('get_user_history', { user_id: userId, hours: 24 }, view, view ? null : '503 from the engine', 38);
  let graphRef = -1;
  if (kind === 'money' && graph) {
    graphRef = addTool('get_graph_neighborhood', { user_id: userId, depth: 2 }, graph, null, 44);
  }

  /** @type {{ text: string, refs: number[] }[]} */
  const said = [];
  const say = (/** @type {string} */ text, /** @type {number[]} */ refs) => said.push({ text, refs });

  const score = typeof d.mlScore === 'number' ? d.mlScore : null;
  const top = Array.isArray(d.contributions)
    ? [...d.contributions].filter((c) => c && c.shap > 0).sort((a, b) => b.shap - a.shap)[0] || null
    : null;

  const sayVelocity = () => {
    if (!velocity) return;
    const e = velocity.evidence || {};
    say(`The account made ${e.count} payments in ${e.windowSecs} seconds, against a limit of ${e.limit}.`, [0]);
    if (typeof e.sum === 'number') say(`Together they moved ₹${group(e.sum)} inside that window.`, [0]);
  };
  const sayGeo = () => {
    const g = byCode('GEO_IMPOSSIBLE');
    if (!g) return;
    const e = g.evidence || {};
    say(`Consecutive payments were ${group(e.distanceKm)} km apart but only ${e.gapSecs} seconds apart, an implied ${group(e.speedKmh)} km/h.`, [0]);
    say(`The engine treats anything over ${e.maxSpeedKmh} km/h as impossible, faster than a commercial flight.`, [0]);
  };
  const sayRing = () => {
    const r = byCode('RING_SUSPECT');
    if (r) {
      const e = r.evidence || {};
      const cycle = Array.isArray(e.cycle) ? e.cycle : [];
      if (cycle.length > 2) {
        say(`This payment to ${cycle[1]} closed a loop: the money came back to ${cycle[0]} through ${listOf(cycle.slice(2, -1))}.`, [0]);
      }
      if (typeof e.componentSize === 'number') say(`The accounts involved sit in a connected cluster of ${e.componentSize} accounts.`, [0]);
    }
    const p = byCode('PASS_THROUGH');
    if (p) {
      const e = p.evidence || {};
      say(`It forwarded ${Math.round(e.ratio * 100)}% of ₹${group(e.inboundAmount)} that arrived from ${e.inboundFrom} ${e.secsSinceInbound} seconds earlier.`, [0]);
    }
    if (graphRef >= 0 && Array.isArray(graph.edges) && graph.edges.length > 0) {
      const n = graph.edges.length;
      say(`Within two hops of this account the graph holds ${n} transfer${n === 1 ? '' : 's'} between ${graph.nodes.length} accounts.`, [graphRef]);
    }
  };
  const sayMerchant = () => {
    const m = byCode('HARD_BLOCK_MERCHANT');
    if (!m) return;
    const e = m.evidence || {};
    say(`${e.merchantId} is on the sanctions blocklist, so any payment to it is blocked by a hard rule.`, [0]);
    say('Hard rules run before the model, so no score can release a payment to a blocked merchant.', [0]);
  };
  const sayModel = () => {
    if (score === null) return;
    say(`The model scored this payment ${score.toFixed(4)}${top ? `, with ${top.feature} pushing hardest toward fraud` : ''}.`, [0]);
  };
  const sayHabits = () => {
    if (view && view.amountProfileLifetime) {
      const p = view.amountProfileLifetime;
      say(`Over ${p.transactions} earlier payments this account spent ₹${group(p.meanAmount)} on average.`, [historyRef]);
    }
    const f = d.features || {};
    if (typeof f.amtZ === 'number' && Math.abs(f.amtZ) >= 3) {
      say(`This payment sits ${Math.abs(f.amtZ)} standard deviations ${f.amtZ > 0 ? 'above' : 'below'} the account's usual amount.`, [0]);
    }
    if (view && view.decisionsInPeriod >= 3) {
      say(`The engine decided ${view.decisionsInPeriod} of its payments in the last ${view.periodHours} hours.`, [historyRef]);
    }
  };
  const sayWhy = () => {
    sayVelocity();
    sayGeo();
    sayRing();
    sayMerchant();
    if (said.length === 0) say(`No rule fired on this payment; the verdict was ${d.verdict}.`, [0]);
    sayModel();
  };

  if (kind === 'normal') {
    sayHabits();
    if (said.length === 0) sayWhy();
  } else if (kind === 'change') {
    if (velocity) {
      const e = velocity.evidence || {};
      say(`The burst rule fires above ${e.limit} payments in ${e.windowSecs} seconds; this account made ${e.count}, so a slower pace would not have fired it.`, [0]);
    }
    const g = byCode('GEO_IMPOSSIBLE');
    if (g) say(`Evidence that the card really was ${group(g.evidence.distanceKm)} km away, such as a boarding pass, would explain the jump.`, [0]);
    if (byCode('RING_SUSPECT')) say('A documented business reason for money returning to its origin would weaken the ring signal.', [0]);
    if (byCode('HARD_BLOCK_MERCHANT')) say('Nothing about the account changes this verdict: the merchant itself is blocked.', [0]);
    sayModel();
  } else if (kind === 'spree') {
    sayVelocity();
    const cat = categoryWord(d.merchantCategory);
    say(`This payment went to ${d.merchantId || 'a merchant'}${cat ? `, ${/^[aeiou]/.test(cat) ? 'an' : 'a'} ${cat} merchant` : ''}.`, [0]);
  } else if (kind === 'trip') {
    sayGeo();
  } else if (kind === 'money') {
    sayRing();
    if (said.length === 0) sayWhy();
  } else if (kind === 'merchant') {
    sayMerchant();
    if (said.length === 0) sayWhy();
  } else {
    sayWhy();
  }

  // The one claim the "verifier" removes: a number the cited evidence does not contain.
  const failed = !view;
  const n = absentInteger(failed ? null : evidence[historyRef].payload, 12);
  const removedText = `This account has been flagged ${n} times this week.`;
  const reason = failed
    ? `evidence_refs [${historyRef}] point at tool calls that failed and carry no data`
    : `claim quotes ${n}, which does not appear in evidence [${historyRef}]`;

  steps.push({ kind: 'draft', label: 'Drafted an answer', ms: 1830 });
  steps.push({ kind: 'verify', label: `Checked ${said.length + 1} claim(s) against the evidence, removed 1`, ms: 2 });

  return {
    caseId: detail.caseId,
    question,
    answer: said.map((s) => ({ ...s, verified: true })),
    removed: [{ text: removedText, reason }],
    evidence,
    steps,
    // Contract §2: passed is true whenever an answer survived; violations lists every rejection.
    verification: {
      passed: said.length > 0,
      attempts: 1,
      violations: [{ finding_index: said.length, kind: failed ? 'failed_tool_ref' : 'uncited_number', detail: reason }],
    },
    model,
    latencyMs: steps.reduce((t, s) => t + (s.ms || 0), 0) + 207,
    mode,
  };
}

/**
 * The history as the agent shows it to the model (contract §2): a view, not
 * the raw endpoint payload, and deliberately without the live window counts.
 * @param {string} userId
 * @param {any} history
 */
function historyView(userId, history) {
  if (!history || (!history.profile && !(Array.isArray(history.recent) && history.recent.length))) return null;
  const recent = Array.isArray(history.recent) ? history.recent : [];
  return {
    userId,
    amountProfileLifetime: history.profile
      ? { transactions: history.profile.n, meanAmount: history.profile.mean, stdAmount: history.profile.std }
      : null,
    periodHours: typeof history.hours === 'number' ? history.hours : 24,
    decisionsInPeriod: recent.length,
    latestDecisions: recent.slice(0, 5).map((/** @type {any} */ r) => ({
      verdict: r.verdict,
      firedRules: r.firedRules,
      mlScore: r.mlScore,
      decidedAt: r.decidedAt,
    })),
  };
}

/** @param {string} q */
function questionKind(q) {
  const s = q.toLowerCase();
  if (s.includes('normal')) return 'normal';
  if (s.includes('change the verdict')) return 'change';
  if (s.includes('shopping')) return 'spree';
  if (s.includes('trip')) return 'trip';
  if (s.includes('money come from')) return 'money';
  if (s.includes('merchant')) return 'merchant';
  return 'why';
}

/** @param {string[]} items */
function listOf(items) {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

/** @type {Record<string, string>} */
const CATEGORY = {
  GROC: 'grocery', FOOD: 'food', FUEL: 'fuel', RETAIL: 'retail', PHARM: 'pharmacy', TRAVEL: 'travel',
  ELEC: 'electronics', GIFT: 'gift-card', CRYPTO: 'crypto', GAMBLING: 'gambling', P2P: 'peer-to-peer',
};

/** @param {unknown} code */
function categoryWord(code) {
  return typeof code === 'string' ? CATEGORY[code] || code.toLowerCase() : null;
}

/** 20122.3 → "20,122", 3887.92 → "3,888": what a writer would quote, inside the verifier's 1%. */
function group(/** @type {number} */ n) {
  return Math.round(n).toLocaleString('en-US');
}

/** The first integer ≥ start that appears nowhere in the payload. */
function absentInteger(/** @type {unknown} */ payload, /** @type {number} */ start) {
  const found = new Set();
  const walk = (/** @type {unknown} */ v) => {
    if (typeof v === 'number') found.add(Math.round(v));
    else if (typeof v === 'string') for (const m of v.matchAll(/\d+(?:\.\d+)?/g)) found.add(Math.round(Number(m[0])));
    else if (Array.isArray(v)) {
      found.add(v.length);
      v.forEach(walk);
    } else if (v && typeof v === 'object') {
      found.add(Object.keys(v).length);
      Object.values(v).forEach(walk);
    }
  };
  walk(payload);
  let n = start;
  while (found.has(n)) n += 1;
  return n;
}
