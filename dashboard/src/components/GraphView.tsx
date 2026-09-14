import { useMemo } from 'react';
import type { Neighborhood } from '../lib/types';
import { fmtDateTime, fmtMoney } from '../lib/format';

/**
 * Hand-authored inline SVG, deliberately not a graph library: neighbourhoods are
 * a handful of nodes (≤ 50 edges per node, depth ≤ 2), so a radial BFS layout in
 * ~60 lines beats pulling in react-force-graph.
 */

const W = 380;
const H = 300;
const CX = W / 2;
const CY = H / 2;
const RING = [0, 88, 148];

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
    if (!adj.has(id)) adj.set(id, new Set());
    return adj.get(id)!;
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
      for (const nb2 of adj.get(id) ?? []) {
        if (!hop.has(nb2)) {
          hop.set(nb2, d + 1);
          next.push(nb2);
        }
      }
    }
    frontier = next;
    d += 1;
  }

  const byHop = new Map<number, string[]>();
  for (const n of nb.nodes) {
    const h = hop.get(n.id) ?? RING.length - 1; // unreachable → outer ring
    if (!byHop.has(h)) byHop.set(h, []);
    byHop.get(h)!.push(n.id);
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
        x: CX + Math.cos(a) * r,
        y: CY + Math.sin(a) * r * 0.85, // squash vertically, the box is wider than tall
        hop: h,
      });
    });
  }
  return placed;
}

export function GraphView({ nb }: { nb: Neighborhood }) {
  const placed = useMemo(() => layout(nb), [nb]);
  const pos = useMemo(() => new Map(placed.map((p) => [p.id, p])), [placed]);

  if (nb.nodes.length === 0) {
    return (
      <p className="state state--empty">
        No P2P edges for this user in the last 24h — nothing to draw. (Card-only
        spend never enters the transaction graph.)
      </p>
    );
  }

  const showAmounts = nb.edges.length <= 8;

  return (
    <figure className="graph">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="graph__svg"
        role="img"
        aria-label={`Transaction neighbourhood of ${nb.userId}: ${nb.nodes.length} accounts, ${nb.edges.length} transfers`}
      >
        <defs>
          <marker
            id="fg-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" className="graph__arrowhead" />
          </marker>
        </defs>

        {nb.edges.map((e, i) => {
          const a = pos.get(e.src);
          const b = pos.get(e.dst);
          if (!a || !b) return null;
          // Trim the line to the node radius so the arrowhead sits on the rim.
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const len = Math.hypot(dx, dy) || 1;
          const rb = b.id === nb.userId ? 20 : 15;
          const ra = a.id === nb.userId ? 20 : 15;
          const x1 = a.x + (dx / len) * ra;
          const y1 = a.y + (dy / len) * ra;
          const x2 = b.x - (dx / len) * rb;
          const y2 = b.y - (dy / len) * rb;
          return (
            <g className="graph__edge" key={`${e.src}->${e.dst}-${i}`}>
              <title>{`${e.src} → ${e.dst}\n${fmtMoney(e.amount)}\n${fmtDateTime(e.ts)}`}</title>
              <line x1={x1} y1={y1} x2={x2} y2={y2} markerEnd="url(#fg-arrow)" />
              {showAmounts ? (
                <text
                  x={(x1 + x2) / 2}
                  y={(y1 + y2) / 2 - 4}
                  className="graph__edgelabel"
                  textAnchor="middle"
                >
                  {fmtMoney(e.amount)}
                </text>
              ) : null}
            </g>
          );
        })}

        {placed.map((p) => {
          const isRoot = p.id === nb.userId;
          return (
            <g className={`graph__node ${isRoot ? 'graph__node--root' : ''}`} key={p.id}>
              <title>{`${p.id} — degree ${p.degree}${isRoot ? ' (this case)' : ''}`}</title>
              <circle cx={p.x} cy={p.y} r={isRoot ? 20 : 15} />
              <text x={p.x} y={p.y + 4} textAnchor="middle" className="graph__degree">
                {p.degree}
              </text>
              <text
                x={p.x}
                y={p.y + (isRoot ? 34 : 29)}
                textAnchor="middle"
                className="graph__id"
              >
                {p.id}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="graph__caption">
        {nb.nodes.length} accounts · {nb.edges.length} transfers · depth {nb.depth} · component
        size {nb.componentSize}. The number inside a node is its degree; the highlighted node is
        this case&rsquo;s user. Hover an edge for amount and time.
      </figcaption>
    </figure>
  );
}
