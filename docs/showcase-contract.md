# Showcase contract

The single source of truth for the public-facing console: the new `/agent` chat endpoint, the
static replay format, and how the dashboard switches between them. The frontend and the
backend are built against this file in parallel, so a change here is a change to both.

## 1. Modes

The dashboard runs in one of two data modes, chosen at build time:

| `VITE_DATA_MODE` | Data comes from | Used for |
|---|---|---|
| `live` (default) | case-service over HTTP + WebSocket, agent over HTTP | local dev, `make demo`, a live VM, the share tunnel |
| `replay` | static JSON under `/showcase/`, no backend at all | the permanent public URL on GitHub Pages |

`VITE_READ_ONLY=true` additionally hides every control that mutates state (the case status
control). Set it for any public deployment, live or replay.

Replay is a **recording of the real pipeline**, not synthetic UI data. Every tick, case,
report and chat answer in it was produced by the running system and is replayed at its
original timing. The UI must say so plainly: a persistent `REPLAY` badge, and one line in the
intro explaining that the console is replaying a recorded session and that live mode exists.

## 2. The ask endpoint (new)

Routed by nginx: browser `/agent/*` → `analyst-agent:8000/*` (prefix stripped). Vite dev proxy
does the same to `http://localhost:8010`.

### `POST /agent/cases/{caseId}/ask`

Request:

```json
{
  "question": "Why was this transaction flagged?",
  "history": [
    {"role": "user", "content": "Why was this flagged?"},
    {"role": "assistant", "content": "18 transactions in 60 seconds..."}
  ]
}
```

`history` is optional, at most the last 6 turns; the server ignores anything older.

Response `200`:

```json
{
  "caseId": "388d1ab0-bf89-41c8-a72b-3d1ec1ff8ab8",
  "question": "Why was this transaction flagged?",
  "answer": [
    {"text": "The account made 18 transactions in 60 seconds, more than double the limit of 8.", "refs": [0], "verified": true},
    {"text": "The model scored it 0.9998, with the one-minute count contributing most.", "refs": [0], "verified": true},
    {"text": "The merchant is a gift-card seller, a common cash-out route.", "refs": [0], "verified": true}
  ],
  "removed": [
    {"text": "This account has been flagged 12 times this week.", "reason": "claim quotes 12, which does not appear in evidence [2]"}
  ],
  "evidence": [
    {"index": 0, "tool": "decision", "args": {"txnId": "1af96d0e-..."}, "payload": {"verdict": "BLOCK", "signals": [], "features": {}, "contributions": []}},
    {"index": 1, "tool": "get_window_counts", "args": {"user_id": "u_20668"}, "payload": {"cnt1m": 18, "cnt5m": 24, "cnt1h": 37}},
    {"index": 2, "tool": "get_user_history", "args": {"user_id": "u_20668", "hours": 24}, "error": "503 from the engine"}
  ],
  "steps": [
    {"kind": "evidence", "label": "Loaded the decision and its signals", "ms": 12},
    {"kind": "tool", "label": "get_window_counts(u_20668)", "ms": 41},
    {"kind": "draft", "label": "Drafted an answer", "ms": 1830},
    {"kind": "verify", "label": "Checked 4 claims against the evidence, removed 1", "ms": 2}
  ],
  "verification": {"passed": true, "attempts": 1, "violations": []},
  "model": "openai/gpt-oss-120b",
  "latencyMs": 2140,
  "mode": "live"
}
```

A response served from the answer cache also carries `"cached": true`; the same question
about the same case (case, whitespace and a trailing `?` ignored) is answered once per hour.

Rules the UI can rely on:

- `answer[i].refs` index into this response's own `evidence` array, never into the case
  report's evidence. The response is self-contained.
- `evidence[i].index === i`, always, and each entry has exactly one of `payload` or `error`.
- Evidence `0` is always the decision document for the case (tool `"decision"`).
- Every sentence in `answer` survived the citation check. Sentences that failed it are in
  `removed` with the reason, and are **never** shown as part of the answer. Showing the count
  ("the verifier removed 1 unsupported claim") and letting the user expand it is encouraged:
  it is the most direct demonstration of the guard.
- `answer` may be empty if nothing survived verification. The UI then says the analyst could
  not produce a supportable answer, and shows `removed`.
- `verification.passed` is `true` when `answer` is non-empty (every sentence in it is
  verified by construction). `verification.violations` lists every rejection along the way,
  including ones a rewrite fixed, so it can be non-empty while `passed` is true.
- `steps[].detail` is present on a failed tool call or model call, with the error text.
- A `get_user_history` evidence entry is a *view* of the history, not the raw endpoint
  payload: `{userId, amountProfileLifetime: {transactions, meanAmount, stdAmount},
  periodHours, decisionsInPeriod, latestDecisions: [{verdict, firedRules, mlScore,
  decidedAt}]}`. The live window counts are deliberately absent (models read them as a
  typical rate). Render it as-is; it is exactly what the model saw.
- Some questions fetch evidence before the model is called (history for "normal / usual /
  genuine ..." questions, the graph for "where did the money go / ring ..." questions), so a
  `tool` step can come before the first `draft` step.

Errors:

| Status | Meaning | UI should say |
|---|---|---|
| `404` | unknown case | the case no longer exists |
| `429` | rate limited: `Retry-After` header in seconds, and `retryAfterSeconds` in the body | the public demo is rate-limited to protect a free API quota; try again in N s |
| `503` | no model configured or the provider is down, **or** the case service is unreachable; `detail` says which | the analyst is offline in this deployment; everything else still works (for the first); the case service is unreachable (for the second) |

An agent that predates this endpoint answers `404` for every path. Tell the two apart with
`/agent/health` rather than by guessing: an agent that can take questions includes an `ask`
object there (below).

### `GET /agent/health`

`{"status": "UP" | "NO_MODEL", "model": "...", "provider": "...", "ask": {"rateLimited": bool,
"cacheTtlSeconds": n}}`. The UI uses it to decide whether the chat input is enabled in live
mode; the presence of `ask` is the capability check for this endpoint.

### Suggested questions

Client-side, derived from the case's fired rules. Always offer:

- "Why was this transaction flagged?"
- "Is this normal behaviour for this account?"
- "What evidence would change the verdict?"

Plus, by fired rule:

| Rule | Question |
|---|---|
| `VELOCITY_*` | "Could this be a genuine shopping spree?" |
| `GEO_IMPOSSIBLE` | "Could this be a real trip?" |
| `RING_SUSPECT`, `PASS_THROUGH` | "Where did the money come from, and where did it go?" |
| `HARD_BLOCK_MERCHANT` | "Why is this merchant blocked outright?" |

In replay mode only recorded questions can be answered; offer exactly those (see §3), in the
order of the file, and show free text as disabled with a one-line note that free-form
questions work in live mode. The recorder writes "Why was this transaction flagged?" first,
then the pattern's own question, then "What evidence would change the verdict?".

## 3. Replay format

Served as static files under `<base>/showcase/`. All JSON, UTF-8.

| File | Shape |
|---|---|
| `manifest.json` | see below |
| `feed.json` | `{"ticks": [DecisionTick & {"at": number}]}`, `at` = ms since recording start, ascending |
| `cases.json` | `{"items": CaseSummary[], "total": number}`, newest first |
| `cases/{caseId}.json` | `CaseDetail`, exactly as `GET /cases/{id}` returns it |
| `history/{userId}.json` | `UserHistory`, exactly as `GET /internal/users/{id}/history` |
| `graph/{userId}.json` | `Neighborhood`, exactly as `GET /internal/graph/{id}/neighborhood` |
| `ask/{caseId}.json` | `{"answers": AskResponse[]}`, one per recorded question; `{"answers": []}` for a case with none |

Every case in `cases.json` has its `cases/`, `ask/`, `history/` and `graph/` files, so the
replay never requests a file that is not there. `cases.json` is the index of openable cases.

`manifest.json`:

```json
{
  "recordedAt": "2026-09-29T16:02:11Z",
  "durationMs": 240000,
  "tps": 50,
  "scorerModel": "v3",
  "agentModel": "openai/gpt-oss-120b via Groq",
  "stats": {"byStatus": {"OPEN": 212}, "total": 212, "last1h": {"cases": 212, "review": 31, "block": 181}},
  "featured": [
    {"caseId": "…", "pattern": "RING", "title": "A five-account laundering ring", "blurb": "Money went A→B→C→D→E→A in 14 minutes. The closing hop gave it away."},
    {"caseId": "…", "pattern": "GEO", "title": "Delhi, then Chennai, 5 minutes later", "blurb": "…"},
    {"caseId": "…", "pattern": "VELOCITY", "title": "18 card payments in a minute", "blurb": "…"},
    {"caseId": "…", "pattern": "POLICY", "title": "A payment to a sanctioned merchant", "blurb": "…"}
  ]
}
```

Replay behaviour:

- The feed replays `ticks` at their recorded `at` offsets and loops. On loop, reset the
  ticker cleanly; do not show a jump.
- Only cases present under `cases/` open a detail view. A tick whose `caseId` has no file is
  shown in the ticker but not clickable, with no error.
- Missing `history`/`graph` files render the panel's normal "not recorded" empty state.
- Throughput and latency in the header are computed client-side from the replayed ticks,
  exactly as in live mode (each tick carries `latencyMs`), so the numbers mean the same
  thing in both modes.

## 4. Types added to `src/lib/types.ts`

```ts
export interface AnswerSentence { text: string; refs: number[]; verified: boolean }
export interface RemovedClaim { text: string; reason: string }
export interface AskStep { kind: 'evidence' | 'tool' | 'draft' | 'verify'; label: string; detail?: string; ms?: number }
export interface AskResponse {
  caseId: string; question: string;
  answer: AnswerSentence[]; removed: RemovedClaim[];
  evidence: EvidenceEntry[]; steps: AskStep[];
  verification: Verification; model: string; latencyMs: number; mode: 'live' | 'replay';
}
export interface ChatTurn { role: 'user' | 'assistant'; content: string }
export interface ShowcaseManifest { /* §3 */ }
```

`EvidenceEntry`, `Verification` and `Violation` already exist from the report panel and are
reused unchanged.

## 5. New signal code

`PASS_THROUGH`: an outgoing peer-to-peer transfer that forwards a recent inbound transfer at
a similar amount, the layering pattern. Evidence:

```json
{"inboundFrom": "u_14106", "inboundAmount": 41230.5, "outboundAmount": 39612.0,
 "ratio": 0.961, "secsSinceInbound": 184, "chainDepth": 2, "counterpartyId": "u_20190"}
```

Render it like the others, in words: "Forwarded 96% of ₹41,230 received from u_14106 three
minutes earlier; the money has now passed through 2 accounts in a row."

The decision's `features` gain `passThroughRatio`, `secsSinceInbound` (−1 when nothing arrived
within the window) and `chainDepth`. Neighborhood edges from `/internal/graph/{id}/neighborhood`
are `{src, dst, amount, tsMs, chainDepth}`: an epoch-millisecond `tsMs` where the first version
had an ISO `ts`, and `chainDepth` > 0 on an edge that forwarded money it had just received.

## 6. The feed

`/ws/feed` sends JSON arrays of `DecisionTick` about five times a second, starting with a
backfill of the most recent ticks. The case service consumes decisions at least once, so a
consumer rebalance can replay some; the broadcaster drops any `txnId` it has already published
(within the last 20,000), and clients may still de-duplicate defensively.
