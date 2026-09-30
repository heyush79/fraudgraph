import { useMemo } from 'react';
import type { Neighborhood } from '../lib/types';
import { fmtDateTime, fmtMoney0 } from '../lib/format';

/**
 * Hand-authored inline SVG, deliberately not a graph library: neighbourhoods are
 * a handful of nodes (≤ 50 edges per node, depth ≤ 2), so a radial BFS layout in
 * ~60 lines beats a force-directed dependency.
 */

const W = 560;
const H = 300;
const CX = W / 2;
const CY = H / 2 - 8;
const RING = [0, 84, 132];
// The box is wider than tall: stretch rings horizontally, squash them vertically.
const SX = 1.6;
const SY = 0.86;

interface Placed {
  id: string;
  degree: number;
  x: number;
  y: number;
  hop: number;
}

function layout(nb: Neighborhood): Placed[] {
  const adj = new Map<string, Set<string>>();
  const touch = (id: string) => {
    let s = adj.get(id);
    if (!s) {
      s = new Set();
      adj.set(id, s);
    }
    return s;
  };
  for (const n of nb.nodes) touch(n.id);
  for (const e of nb.edges) {
    touch(e.src).add(e.dst);
    touch(e.dst).add(e.src);
  }

  // BFS hop distance from the case's user.
  const hop = new Map<string, number>();
  if (adj.has(nb.userId)) hop.set(nb.userId, 0);
  let frontier = [nb.userId];
  let d = 0;
  while (frontier.length && d < RING.length - 1) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const other of adj.get(id) ?? []) {
        if (!hop.has(other)) {
          hop.set(other, d + 1);
          next.push(other);
        }
      }
    }
    frontier = next;
    d += 1;
  }

  const byHop = new Map<number, string[]>();
  for (const n of nb.nodes) {
    const h = hop.get(n.id) ?? RING.length - 1; // unreachable → outer ring
    const list = byHop.get(h) ?? [];
    list.push(n.id);
    byHop.set(h, list);
  }

  const degreeOf = new Map(nb.nodes.map((n) => [n.id, n.degree]));
  const placed: Placed[] = [];
  for (const [h, ids] of [...byHop.entries()].sort((a, b) => a[0] - b[0])) {
    const r = RING[Math.min(h, RING.length - 1)];
    ids.sort();
    ids.forEach((id, i) => {
      if (r === 0 && ids.length === 1) {
        placed.push({ id, degree: degreeOf.get(id) ?? 0, x: CX, y: CY, hop: h });
        return;
      }
      // Offset alternate rings so hop-1 and hop-2 nodes don't line up.
      const a = (i / ids.length) * Math.PI * 2 - Math.PI / 2 + (h % 2 ? 0 : Math.PI / ids.length);
      placed.push({
        id,
        degree: degreeOf.get(id) ?? 0,
        x: CX + Math.cos(a) * r * SX,
        y: CY + Math.sin(a) * r * SY,
        hop: h,
      });
    });
  }
  return placed;
}

/** Edge times arrive as `tsMs` (current engine) or an ISO `ts` (older payloads). */
function edgeTime(e: Neighborhood['edges'][number]): string {
  if (typeof e.tsMs === 'number') return fmtDateTime(new Date(e.tsMs).toISOString());
  return fmtDateTime(e.ts);
}

/** Directed edges that lie on any of the given cycles, as "src>dst". */
function cycleEdges(cycles: readonly (readonly string[])[]): Set<string> {
  const out = new Set<string>();
  for (const c of cycles) {
    for (let i = 0; i + 1 < c.length; i++) out.add(`${c[i]}>${c[i + 1]}`);
  }
  return out;
}

export function GraphView({ nb, cycles = [] }: { nb: Neighborhood; cycles?: readonly (readonly string[])[] }) {
  const placed = useMemo(() => layout(nb), [nb]);
  const pos = useMemo(() => new Map(placed.map((p) => [p.id, p])), [placed]);
  const onCycle = useMemo(() => cycleEdges([...(nb.cycles ?? []), ...cycles]), [nb.cycles, cycles]);
  const cycleNodes = useMemo(() => {
    const s = new Set<string>();
    for (const k of onCycle) for (const id of k.split('>')) s.add(id);
    return s;
  }, [onCycle]);

  if (nb.nodes.length <= 1 && nb.edges.length === 0) {
    return (
      <p className="state state--empty">
        {cycles.length > 0
          ? 'The engine keeps transfers in its graph for 24 hours, and none remain for this account. The cycle it recorded when it made the decision is shown under “Why it was flagged”.'
          : 'No peer-to-peer transfers for this account in the last 24 hours, so there is nothing to draw. Card and UPI payments never enter the transaction graph.'}
      </p>
    );
  }

  const showAmounts = nb.edges.length <= 10;
  const anyCycle = nb.edges.some((e) => onCycle.has(`${e.src}>${e.dst}`));
  const anyChain = nb.edges.some((e) => (e.chainDepth ?? 0) > 0 && !onCycle.has(`${e.src}>${e.dst}`));

  return (
    <figure className="graph">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="graph__svg"
        role="img"
        aria-label={`Transaction neighbourhood of ${nb.userId}: ${nb.nodes.length} accounts, ${nb.edges.length} transfers${anyCycle ? ', including a cycle' : ''}`}
      >
        <defs>
          <marker id="fg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="graph__arrowhead" />
          </marker>
          <marker id="fg-arrow-hot" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="graph__arrowhead graph__arrowhead--hot" />
          </marker>
          <marker id="fg-arrow-chain" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="graph__arrowhead graph__arrowhead--chain" />
          </marker>
        </defs>

        {nb.edges.map((e, i) => {
          const a = pos.get(e.src);
          const b = pos.get(e.dst);
          if (!a || !b) return null;
          const hot = onCycle.has(`${e.src}>${e.dst}`);
          const chain = !hot && (e.chainDepth ?? 0) > 0;
          // Trim the line to the node radius so the arrowhead sits on the rim.
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const len = Math.hypot(dx, dy) || 1;
          const rb = b.id === nb.userId ? 19 : 14;
          const ra = a.id === nb.userId ? 19 : 14;
          const x1 = a.x + (dx / len) * ra;
          const y1 = a.y + (dy / len) * ra;
          const x2 = b.x - (dx / len) * (rb + 1);
          const y2 = b.y - (dy / len) * (rb + 1);
          return (
            <g
              className={hot ? 'graph__edge graph__edge--hot' : chain ? 'graph__edge graph__edge--chain' : 'graph__edge'}
              key={`${e.src}->${e.dst}-${i}`}
            >
              <title>{`${e.src} → ${e.dst}\n${fmtMoney0(e.amount)}\n${edgeTime(e)}${hot ? '\npart of a cycle' : chain ? '\npassed on money that had just arrived' : ''}`}</title>
              <line
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                markerEnd={hot ? 'url(#fg-arrow-hot)' : chain ? 'url(#fg-arrow-chain)' : 'url(#fg-arrow)'}
              />
              {/* A wider invisible line so the edge is easy to hover. */}
              <line x1={x1} y1={y1} x2={x2} y2={y2} className="graph__hit" />
              {showAmounts ? (
                <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 5} className="graph__edgelabel" textAnchor="middle">
                  {fmtMoney0(e.amount)}
                </text>
              ) : null}
            </g>
          );
        })}

        {placed.map((p) => {
          const isRoot = p.id === nb.userId;
          const cls = ['graph__node', isRoot ? 'graph__node--root' : '', cycleNodes.has(p.id) ? 'graph__node--hot' : '']
            .filter(Boolean)
            .join(' ');
          return (
            <g className={cls} key={p.id}>
              <title>{`${p.id}: ${p.degree} transfer${p.degree === 1 ? '' : 's'}${isRoot ? ' (this case)' : ''}`}</title>
              <circle cx={p.x} cy={p.y} r={isRoot ? 19 : 14} />
              <text x={p.x} y={p.y + 3.5} textAnchor="middle" className="graph__degree">
                {p.degree}
              </text>
              <text x={p.x} y={p.y + (isRoot ? 33 : 28)} textAnchor="middle" className="graph__id">
                {p.id}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="graph__caption">
        {nb.nodes.length} accounts, {nb.edges.length} transfers, depth {nb.depth}; the wider cluster
        holds {nb.componentSize}. The number in a node is its transfer count; the larger node is this
        case&rsquo;s account.{anyCycle ? ' Red edges form a cycle: money that returned to where it started.' : ''}
        {anyChain ? ' Amber edges passed on money that had only just arrived.' : ''}{' '}
        Hover an edge for its amount and time.
      </figcaption>
    </figure>
  );
}
