# FraudGraph console

The public face of FraudGraph: one screen with the live decision feed, the
selected case under investigation, and an "Ask the analyst" chat about that
case. No SSR, no auth, no state library. The backend owns the truth, this
renders it.

```
npm install
npm run dev             # http://localhost:5173, proxies to the running stack
npm run build           # type-check + live-mode bundle into dist/
npm run build:replay    # the same app over static replay files (read-only)
npm run snapshot:sample # write a small replay sample from the running stack
```

## Two data modes

Chosen at build time by `VITE_DATA_MODE` (`docs/showcase-contract.md` is the
contract for both). Views never know which one they have: everything they read
goes through the `DataSource` interface in `src/data/source.ts`.

| Mode | Data from | Built by |
|---|---|---|
| `live` (default) | case service over HTTP + `WS /ws/feed`, analyst agent under `/agent` | `npm run build`, the Dockerfile |
| `replay` | static JSON under `<base>/showcase/`, no backend | `npm run build:replay` |

The replay is a recording of the real pipeline, played back at its original
timing and looped; the header's `REPLAY` badge and the intro strip say so.
Throughput and p50/p99 in the header are computed in the browser from the
ticks' `latencyMs` in both modes, so they mean the same thing either way.

`VITE_READ_ONLY=true` hides the case status control; `build:replay` always sets
it, and any public live deployment should (`--build-arg VITE_READ_ONLY=true`).

GitHub Pages serves the replay from `/fraudgraph/`, so the base path comes from
the environment and every replay fetch is relative to it:

```
VITE_BASE=/fraudgraph/ npm run build:replay
VITE_BASE=/fraudgraph/ npx vite preview --outDir dist   # check it locally
```

### Replay data

`public/showcase/` holds the files, in the format of contract §3. The real
recording is written there by the project's recorder. Until then,
`scripts/snapshot-sample.mjs` (plain Node 22+, no dependencies, GETs and one
WebSocket read only) writes a small development sample from a running stack:
60 s of the real feed, six real cases with their history and graph, and ask
files built from templates, not model answers. Its manifest says
`"sample": true` and the badge reads `REPLAY · SAMPLE`.

## Routes

Hash routes, so the build needs no server configuration under any sub-path.

| Route | What it shows |
|---|---|
| `#/` | The console. Nothing selected: the first featured case (replay) or the latest case with an analyst report (live). |
| `#/case/{id}` | The console with that case selected. `#/cases/{id}` and `#/live` from the old dashboard still resolve. |
| `#/cases` | Every case, filterable by status, 50 a page. |
| `#/about` | What the system is, a hand-drawn architecture diagram, key numbers, links. |

## The console

- **Decision feed** (left). Every decision, newest first, 200 kept; the Flagged
  filter keeps its own 200 flagged decisions. New rows slide in, flagged ones
  flash their verdict colour once, and nothing else in the app moves
  (`prefers-reduced-motion` switches it off). A flagged row opens its case.
- **Case investigation** (centre). Verdict, mode, model score; the fired
  signals in words ("19 payments in 60 seconds, limit 8"); the analyst's report
  with citation chips that open the cited evidence, with the numbers the claim
  quotes marked inside it; SHAP attribution; the account's P2P neighbourhood
  (inline SVG, cycle edges red, pass-through edges amber); recent activity; the
  feature vector; the case timeline. A case whose report has not arrived yet is
  re-read every 5 s for ten minutes.
- **Ask the analyst** (right; a drawer below 1100 px). Suggested questions from
  the fired rules, free text in live mode, answers sentence by sentence with
  citation chips, a collapsed disclosure of anything the verifier removed and
  why, the steps the agent took, and the model and latency. History is kept per
  case while the page is open. 404, 429 (with `Retry-After`) and 503 each get
  their own message; if `/agent/health` is down the input is disabled with one
  line of explanation and the rest of the page works. In replay, exactly the
  recorded questions are offered and free text is disabled.

For working on the chat without spending a model quota, add `?fixture` to the
URL in `npm run dev` (before the `#`): answers are then built from the real case
by `src/data/askFixture.js` and labelled `DEV FIXTURE`. Production bundles do
not contain the fixture.

## Layout

At 1100 px and wider the three panes sit side by side, each scrolling on its
own. From 700 to 1099 px the chat becomes a slide-over drawer. Below 700 px
everything stacks and the page scrolls; tested at 400 px with no horizontal
scroll.

## Dependencies

| Package | Why |
|---|---|
| `react`, `react-dom` | the whole runtime |
| `vite`, `@vitejs/plugin-react` | dev server + build |
| `typescript`, `@types/react`, `@types/react-dom` | the contract is written down in `src/lib/types.ts` and checked at compile time |

Nothing else. The router is ~40 lines (`src/lib/useHashRoute.ts`); the two
shared stores (`src/lib/feedStore.ts`, `src/lib/chatStore.ts`) use React's own
`useSyncExternalStore`; the graph, the SHAP bars and the architecture diagram
are hand-written SVG and CSS.

## Conventions

- Colours are tokens in `src/styles/tokens.css`: dark is the base design, light
  re-points the same names, `data-theme` on `<html>` overrides
  `prefers-color-scheme` once the viewer picks one (stored in `localStorage`,
  every access wrapped so a blocked store only loses the preference). No
  component names a literal colour.
- Verdict colour is semantic and always travels with the word.
- IBM Plex Sans for text, IBM Plex Mono for ids, amounts, scores, codes and
  every number in a column (tabular figures), Bricolage Grotesque for the
  product name and the About headings.
- Every panel handles loading, error, empty and (in replay) not-recorded
  separately; a failed refresh keeps the last good data on screen.

## Production

```bash
docker build -t fraudgraph-dashboard .                                   # live mode
docker build --build-arg VITE_READ_ONLY=true -t fraudgraph-dashboard .   # public live
docker run --rm -p 8080:80 fraudgraph-dashboard
```

nginx serves `dist/` and proxies `/cases`, `/stats`, `/internal` and `/ws` to
`case-service:8082` (`/ws` with the upgrade headers and a long read timeout) and
`/agent/*` to `analyst-agent:8000/*` with the prefix stripped. The agent's
address is resolved per request, so the image still starts in a deployment
without the agent; the chat then says the analyst is unreachable.

## Assumptions about the contract

- Ticks inside one `/ws/feed` batch are chronological; the first frame after a
  connect is the server's backfill (drawn without animation, and excluded from
  throughput when it is older than 15 s). Ticks are de-duplicated by `txnId`,
  since every reconnect re-sends the backfill.
- Replay: `cases.json` doubles as the index of which `cases/{id}.json` files
  exist, so unrecorded cases are shown but never fetched.
- A 404 from the ask endpoint is checked against the case service: if the case
  exists, the deployed agent predates the endpoint and the chat says so rather
  than claiming the case is gone.
- Amounts are rupees, formatted `en-IN`.
