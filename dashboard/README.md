# FraudGraph dashboard

A thin React window into the case service. No SSR, no auth, no state library — the
backend owns the truth, this renders it.

```
npm install
npm run dev       # http://localhost:5173, proxies the API to :8082
npm run build     # type-check + production bundle into dist/
npm run preview   # serve the built bundle (no API proxy — see below)
```

The dev server proxies `/cases`, `/stats`, `/internal` and `/ws` (with
`ws: true`) to `http://localhost:8082`, so the app is same-origin in dev exactly
as it is in production. Start the case service first; every view degrades to a
readable error if it is down.

To point a dev build at a case service somewhere else, set `VITE_API_BASE`
(see `.env.example`). Unset — the default — means same-origin, which is what the
nginx image relies on.

## Views

| Route | What it shows |
|---|---|
| `#/live` | **Live feed.** Every decision the engine emits, over `WS /ws/feed`, newest first, 200 rows kept in memory. Colour-coded by verdict, with time, user, verdict, mode, model score, fired rules and end-to-end latency. Rows that carry a `caseId` are clickable and open the case. Filter chips (all / flagged / per verdict), plus pause and clear — the ticker moves fast during a demo. |
| `#/cases` | **Cases table.** Filter by status, 50 per page, `total` from the API drives the pager. Click a row for the detail. |
| `#/cases/{caseId}` | **Case detail.** See below. |

The header carries `/stats` (polled every 10s): the per-status case counts — each
one a link into the filtered table — and the last-hour case / block / review
counts. The connection pill reflects the real socket state (`Live` /
`Connecting` / `Disconnected`, with the retry count); clicking it forces an
immediate reconnect.

### Case detail

- **Verdict card** — verdict, mode, model score, decision latency, ids, fired
  rules, and the status control (a `PATCH /cases/{id}/status` per change, with
  its own saving and error state).
- **Signals** — each signal's evidence rendered as a sentence rather than a JSON
  blob: a velocity signal reads "18 transactions in 60s — the limit is 8 (2.3×
  over)"; a geo signal states distance, gap and the implied speed against the
  ceiling; a ring signal draws the cycle as a chain of user ids. An unknown
  signal code falls back to a key/value table, so the engine can add rules
  without this file changing first.
- **Model attribution** — SHAP contributions as signed horizontal bars around a
  zero axis. Right and red pushed the model toward fraud, left and green pulled
  it away; every bar is directly labelled so colour is never the only cue.
- **Feature vector** — exactly what went to the scorer.
- **Analyst report** — renders the agent's summary, fraud type, confidence and
  cited findings. Until Phase 5 lands, `reportDoc` is null and the panel says so.
- **Transaction neighbourhood** — `GET /internal/graph/{userId}/neighborhood?depth=2`
  drawn as a hand-authored inline SVG: radial BFS layout, the case's user at the
  centre, degree inside each node, direction arrows, amount on each edge (hover
  for amount and time). No graph library — these neighbourhoods are a handful of
  nodes.
- **User activity** — `GET /internal/users/{userId}/history?hours=24`: the rolling
  amount profile, the 1m/5m/1h window counts and sums, and the last few
  decisions. `profile` and `windows` are null when the engine read API is
  unreachable; the panel says that explicitly instead of showing zeroes.

## Dependencies

| Package | Why |
|---|---|
| `react`, `react-dom` | the whole runtime |
| `vite`, `@vitejs/plugin-react` | dev server + build |
| `typescript`, `@types/react`, `@types/react-dom` | the API contract is written down in `src/lib/types.ts`; the backend is being built in parallel, so a compile-time check on the shape is worth the dev dependency |

Nothing else. Routing is a ~30-line hash router (`src/lib/useHashRoute.ts`) rather
than `react-router-dom`; both charts are hand-written (CSS bars and inline SVG)
rather than a chart or graph library.

## Conventions

- Colour, type and spacing are custom properties defined once on `:root` in
  `src/styles/tokens.css`, with a single `prefers-color-scheme: dark` block that
  re-points the same names. No component stylesheet has a colour media query.
- IBM Plex Sans for text, IBM Plex Mono for ids, codes and numbers, both from
  Google Fonts with real fallback stacks. Numeric columns use `tabular-nums`.
- Every view handles loading, error and empty separately — `Async` in
  `src/components/Bits.tsx` is the one place that decides which to show, and a
  failed refresh keeps the last good data on screen with a warning rather than
  blanking the page.
- Works down to phone width: the ticker reflows into a card per decision, the
  cases table scrolls horizontally, the detail collapses to one column.

## Production

```bash
docker build -t fraudgraph-dashboard .
docker run --rm -p 8080:80 fraudgraph-dashboard
```

Multi-stage: `node:22-alpine` runs `npm ci && npm run build`, then
`nginx:1.27-alpine` serves `dist/` on port 80 with a history fallback, and
proxies `/cases`, `/stats`, `/internal` and `/ws` to `http://case-service:8082`
— `/ws` with the `Upgrade`/`Connection` headers and a long read timeout, since a
quiet feed must not be torn down. It therefore needs to run on the same Docker
network as the case service, with that service name.

## Assumptions about the contract

- Ticks inside one `/ws/feed` batch are assumed chronological; the feed reverses
  a batch so the newest ends up on top. A non-array frame is tolerated as a
  single tick.
- `firedRules` and `signals` may be absent or empty on any decision; every
  numeric field is treated as possibly null.
- Amounts are formatted as INR, matching the generator.
