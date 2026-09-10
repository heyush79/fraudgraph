# FraudGraph — Low-Level Design

Companion to the HLD. Covers repo layout, Kafka contracts, class-level design of every service, state store layouts, algorithms, APIs, DB schema, error handling, and the test strategy. Assumptions: single-node Docker Compose deployment first; every design choice notes its scale-up path.

---

## 1. Repository layout (monorepo)

```
fraudgraph/
├── docker-compose.yml          # kafka, redis, postgres, all services
├── Makefile                    # make demo | make train | make bench
├── proto/
│   └── scoring.proto           # shared gRPC contract (Java + Python codegen)
├── generator/                  # Python — traffic + fraud injection
├── stream-engine/              # Java 17, Spring Boot 3, Kafka Streams
├── ml-scorer/                  # Python, FastAPI(admin) + gRPC(scoring), XGBoost
├── case-service/               # Java 17, Spring Boot 3, Postgres, WebSocket
├── analyst-agent/              # Python, LangGraph + ChromaDB
└── dashboard/                  # React (Vite) — live feed + case view
```

One repo, one `docker compose up`. This matters for the demo: no cross-repo setup instructions.

---

## 2. Kafka contracts

| Topic | Key | Partitions | Retention | Producer → Consumer |
|---|---|---|---|---|
| `transactions.raw` | `userId` | 6 | 24h | generator → stream-engine |
| `transactions.labels` | `txnId` | 3 | 7d | generator → ml-scorer trainer (ground truth; **never** read by the hot path) |
| `fraud.decisions` | `userId` | 6 | 7d, compacted off | stream-engine → case-service |
| `transactions.dlq` | original key | 1 | 7d | stream-engine → manual inspection |

Design notes:

- **Key = `userId` on `transactions.raw`** gives per-user ordering per partition. All stateful checks (windows, last-location, profile) are keyed by user, so co-partitioning makes them correct without global ordering.
- Serde: **JSON via Jackson** for v1 (debuggable with `kcat`). Upgrade path: Avro + Schema Registry — mention this trade-off in the README, it is a classic interview probe.
- `transactions.labels` exists so the trainer never has to parse generator internals. Keeping labels off the hot path is the "no label leakage" story.

### 2.1 Event schemas

```json
// transactions.raw
{
  "txnId": "uuid", "userId": "u_10023", "merchantId": "m_ELEC_0042",
  "counterpartyId": "u_10981|null",       // set for P2P transfers — feeds the graph
  "amount": 1499.00, "currency": "INR",
  "lat": 17.3850, "lon": 78.4867,
  "deviceId": "d_ab12", "channel": "CARD|UPI|P2P",
  "ts": "2026-09-04T10:15:03.120Z"
}

// fraud.decisions
{
  "txnId": "uuid", "userId": "u_10023",
  "verdict": "ALLOW|REVIEW|BLOCK",
  "mode": "FULL|DEGRADED",                 // DEGRADED = scorer breaker open
  "mlScore": 0.91,
  "firedRules": ["VELOCITY_1M", "GEO_IMPOSSIBLE"],
  "features": { "cnt1m": 14, "geoSpeedKmh": 4210.5, "amtZ": 3.8, "inCycle": true },
  "contributions": [ {"feature": "cnt1m", "shap": 0.31}, ... ],
  "latencyMs": 74,
  "decidedAt": "2026-09-04T10:15:03.194Z"
}
```

`fraud.decisions` is the audit log. Replaying it reconstructs system behavior for any window — say this sentence in interviews.

---

## 3. Stream engine (Java) — the core service

### 3.1 Kafka Streams topology

```
transactions.raw
   │
   ▼
[dedupProcessor]           state: dedup-store (txnId → ts, TTL 1h)
   │
   ▼
[enrichProcessor]          state: profile-store, last-location-store  (reads)
   │
   ▼
[checkProcessor]           state: velocity window stores; calls GraphService
   │                        emits RiskSignals; updates profile/location (writes)
   ▼
[decisionProcessor]        calls ScoringClient (gRPC, breaker-wrapped)
   │                        applies RuleEngine + ThresholdPolicy
   ├──────────────► fraud.decisions (sink)
   └──(on error)──► transactions.dlq (sink)
```

Use the **Processor API**, not the DSL, for the check/decision stages — you need punctuators (store cleanup), multiple state stores per processor, and explicit control. Using the DSL for source/sink and PAPI for the middle is idiomatic and a good talking point.

### 3.2 Package structure

```
com.fraudgraph.stream/
├── config/        KafkaStreamsConfig, TopologyBuilder, SerdeFactory
├── model/         Transaction, RiskSignal, FeatureVector, Decision, Verdict(enum)
├── processor/     DedupProcessor, EnrichProcessor, CheckProcessor, DecisionProcessor
├── check/         Check(interface), VelocityCheck, GeoCheck, GraphCheck
├── graph/         TransactionGraph, UnionFind, CycleDetector
├── rules/         Rule(interface), RuleEngine, rules/ (HardBlockMerchantRule, ...)
├── scoring/       ScoringClient(interface), GrpcScoringClient, DegradedScoringClient
├── decision/      ThresholdPolicy, DecisionAssembler
└── profile/       UserProfile, WelfordAccumulator
```

### 3.3 Key interfaces

```java
public interface Check {
    /** Pure function of (txn, state). Never throws — returns empty on internal error. */
    List<RiskSignal> evaluate(Transaction txn, CheckContext ctx);
}

public record RiskSignal(String code, double severity /*0..1*/, Map<String, Object> evidence) {}

public interface Rule {
    int priority();                       // lower runs first
    Optional<Verdict> apply(Transaction txn, List<RiskSignal> signals, double mlScore);
}   // first non-empty verdict wins — chain-of-responsibility, name the pattern in the README

public interface ScoringClient {
    ScoreResult score(FeatureVector fv);  // implementations: gRPC (breaker-wrapped), Degraded
}
```

### 3.4 State stores

| Store | Type | Key → Value | Purpose / cleanup |
|---|---|---|---|
| `dedup-store` | KeyValueStore | txnId → firstSeenTs | at-least-once → exactly-once effect; punctuator evicts > 1h |
| `velocity-1m` / `-5m` / `-1h` | WindowStore | userId → count,sum | sliding windows, retention = window + grace 30s |
| `last-location-store` | KeyValueStore | userId → (lat, lon, ts) | geo check input; overwritten each txn |
| `profile-store` | KeyValueStore | userId → WelfordAccumulator(n, mean, M2) | rolling amount stats |

All stores are RocksDB-backed and changelogged → survive restarts, migrate on rebalance. **Redis is used only for cross-service reads** (agent/case-service reading profiles), not by the hot path — Kafka Streams local state is faster and transactional with the stream. This division is a deliberate, defensible choice.

**Welford's online algorithm** (rolling mean/std without storing history):

```java
void add(double x) { n++; double d = x - mean; mean += d / n; m2 += d * (x - mean); }
double std() { return n > 1 ? Math.sqrt(m2 / (n - 1)) : 0; }
```

Amount z-score = `(amount − mean) / std` (guard std < ε → z = 0, and require n ≥ 10 before trusting z).

### 3.5 The three checks

**VelocityCheck.** Fetch window aggregates for 1m/5m/1h. Thresholds from config. Severity scales with overshoot: `min(1, (count − limit) / limit)`. Evidence = the counts (they go straight into the analyst report).

**GeoCheck.** Haversine distance between `last-location-store` value and current txn; implied speed = km / hours-elapsed. Signal `GEO_IMPOSSIBLE` if speed > 900 km/h (commercial flight) **and** distance > 100 km (kills GPS-jitter false positives). Skip if no prior location or Δt < 60s (division blow-up guard). These two guard clauses are exactly the edge-case thinking interviewers probe for.

**GraphCheck** — the differentiator. `TransactionGraph` is a singleton (one per stream thread; merge-on-read across threads is v2 — note it as a known limitation):

- Adjacency: `Map<String, Deque<Edge>>`, capped at 50 most-recent edges per node; `Edge(dst, amount, ts)` with 24h TTL, lazily evicted on access.
- **Ring detection: bounded DFS** from the txn's source node following outgoing edges, depth ≤ 5, visited-set pruned. A path returning to the source = cycle → `RING_SUSPECT` with the cycle's node list as evidence. Cost O(b^5) worst case with b ≤ 50, in practice tiny because honest users don't form cycles.
- **Union-Find** (path compression + union by rank, amortized ~O(1)) maintains components for the `componentSize` feature and lets the agent ask "who else is in this cluster?"
- Why not Neo4j in v1: a network hop per transaction on the hot path for a graph that fits in memory is the wrong trade — this is your best "justify the boring choice" answer. Neo4j is the v2 path once the graph outgrows heap.

### 3.6 Decision stage

```java
// DecisionProcessor.process(...)
List<RiskSignal> signals = ...;                       // from CheckProcessor
boolean invokeModel = !signals.isEmpty() || sampler.hit(txn.txnId());  // 1% shadow sample
ScoreResult ml = invokeModel ? scoringClient.score(features) : ScoreResult.notScored();
Decision d = thresholdPolicy.decide(txn, signals, ml); // rules first, then thresholds
```

**ThresholdPolicy** (all values in `application.yml`, hot-reloadable via Spring Cloud config or an admin endpoint):

| Condition (first match wins) | Verdict |
|---|---|
| any hard rule fires (sanctioned merchant, amount > absolute cap) | BLOCK |
| mlScore ≥ 0.85 | BLOCK |
| mlScore ≥ 0.60, or ≥ 2 signals with severity ≥ 0.5 | REVIEW |
| scorer DEGRADED and ≥ 1 signal | REVIEW (fail-safe: never auto-block on rules alone in degraded mode, except hard rules) |
| otherwise | ALLOW |

**ScoringClient resilience** (Resilience4j): timeout 150ms; circuit breaker — sliding window 50 calls, open at 50% failure, half-open probe after 10s. Open breaker → `DegradedScoringClient` returns `ScoreResult.degraded()` and the decision carries `mode: DEGRADED`. Every state transition logged + countered (`fraudgraph_breaker_state`).

### 3.7 Error handling

- Poison messages: custom `DeserializationExceptionHandler` → raw bytes + error → `transactions.dlq`, continue.
- Check exceptions: caught inside each `Check`, logged, counted, empty signal list returned — a bug in GeoCheck must never stall the stream.
- Processing guarantee: `processing.guarantee=exactly_once_v2` (EOS). Know what it costs (transactional producer overhead) and say so.

---

## 4. ML scorer (Python)

### 4.1 gRPC contract (`proto/scoring.proto`)

```proto
service ScoringService { rpc Score (FeatureVector) returns (ScoreResult); }

message FeatureVector {
  string txn_id = 1;
  int32 cnt_1m = 2;  int32 cnt_5m = 3;  int32 cnt_1h = 4;
  double sum_1h = 5; double amt_z = 6;  double geo_speed_kmh = 7;
  double secs_since_last = 8;
  int32 merchant_risk_tier = 9;          // 0-3, static lookup table
  int32 node_degree = 10; bool in_cycle = 11; int32 component_size = 12;
  int32 channel = 13;                    // enum CARD=0, UPI=1, P2P=2
}
message ScoreResult {
  double probability = 1;
  repeated Contribution contributions = 2;   // top-5 SHAP values
  string model_version = 3;
}
message Contribution { string feature = 1; double shap = 2; }
```

The proto is the **single source of truth** for the feature vector — Java and Python both codegen from it, so features can't silently drift between training and serving. That sentence is a senior-level talking point.

### 4.2 Service layout

```
ml-scorer/
├── scorer/server.py        # grpc.aio server, loads model at startup
├── scorer/model.py         # ModelBundle: xgb model + SHAP TreeExplainer + version
├── scorer/features.py      # proto ↔ numpy row (ONE place, shared with training)
├── training/train.py       # consumes raw+labels topics → parquet → train → registry/
├── training/evaluate.py    # PR curve, threshold sweep, writes metrics.json
├── registry/               # v3/model.json, v3/meta.json (metrics, feature list, git sha)
└── api/admin.py            # FastAPI: /health, /model, /reload?version=v3
```

### 4.3 Training pipeline

1. `train.py --hours 2` consumes `transactions.raw` joined with `transactions.labels` on `txnId` → pandas frame using **the same `features.py`** as serving.
2. Model: `XGBClassifier(n_estimators=200, max_depth=6, scale_pos_weight=neg/pos)` — class imbalance handled explicitly (fraud ≈ 1–2% of traffic).
3. Split **by time, not randomly** (train on first 80% of the window, test on last 20%) — random splits leak future into past on temporal data. Interviewers who know ML will specifically check whether you know this.
4. `evaluate.py` sweeps thresholds, writes precision/recall/F1 per threshold; you pick the decision thresholds *from this table*, which turns your threshold config from magic numbers into an artifact.
5. Optional second model: `IsolationForest` trained without labels — keep it behind `/score?model=iforest` for the "what if you had no labels" interview conversation.

### 4.4 Serving

- `grpc.aio` with 4 workers; model + explainer loaded once at startup; `/reload` hot-swaps by version directory.
- SHAP via `TreeExplainer` (fast for trees); compute top-5 contributions per call. If p99 exceeds ~40ms budget, compute SHAP only when `probability > 0.4` — scores that will be ALLOW anyway don't need explanations. Nice optimization story.
- Metrics: score histogram, latency histogram, model_version gauge → basis for drift monitoring (v2: PSI between serving and training score distributions).

---

## 5. Case service (Java, Spring Boot)

### 5.1 Postgres schema

```sql
CREATE TABLE cases (
  case_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  txn_id       UUID NOT NULL UNIQUE,          -- idempotent case creation
  user_id      TEXT NOT NULL,
  verdict      TEXT NOT NULL CHECK (verdict IN ('REVIEW','BLOCK')),
  ml_score     DOUBLE PRECISION,
  decision_doc JSONB NOT NULL,                -- full fraud.decisions event
  status       TEXT NOT NULL DEFAULT 'OPEN'
               CHECK (status IN ('OPEN','INVESTIGATING','REPORTED','CLOSED_FRAUD','CLOSED_FP')),
  report_doc   JSONB,                         -- analyst agent output
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_cases_user   ON cases (user_id, created_at DESC);
CREATE INDEX idx_cases_status ON cases (status) WHERE status <> 'CLOSED_FP';

CREATE TABLE case_events (                     -- append-only audit trail per case
  id BIGSERIAL PRIMARY KEY,
  case_id UUID REFERENCES cases,
  event_type TEXT NOT NULL,                    -- CREATED, AGENT_STARTED, REPORT_ATTACHED, STATUS_CHANGED
  payload JSONB, at TIMESTAMPTZ DEFAULT now()
);
```

`UNIQUE(txn_id)` + `INSERT ... ON CONFLICT DO NOTHING` = idempotent consumption of `fraud.decisions` (at-least-once delivery handled at the DB, not in code).

### 5.2 Components

- `DecisionConsumer` (`@KafkaListener` on `fraud.decisions`): every decision → WebSocket broadcast (live feed); REVIEW/BLOCK → upsert case → `POST analyst-agent/investigate {caseId}` (async, fire-and-forget with retry queue).
- REST: `GET /cases?status=`, `GET /cases/{id}`, `PATCH /cases/{id}/status`, plus **agent tool endpoints**: `GET /internal/users/{id}/history?hours=24`, `GET /internal/graph/{userId}/neighborhood?depth=2` (proxied from stream-engine's read API).
- WebSocket `/ws/feed`: decision ticker for the dashboard — this is what makes the demo feel alive.

---

## 6. Analyst agent (Python, LangGraph)

### 6.1 Graph

```
triage → investigate ⟲ (bounded loop, ≤ 8 tool calls) → similar_cases → draft_report → verify → done
                                                                            └─(fail)→ investigate (once)
```

State:

```python
class AgentState(TypedDict):
    case: dict                      # decision_doc from case-service
    evidence: list[Evidence]        # every tool result, tagged with tool+args
    hypotheses: list[str]
    similar: list[dict]             # from Chroma
    report: dict | None
    tool_calls_used: int            # hard budget: 8
```

Tools (each is a thin HTTP client to your own services — the agent has **no direct DB or Kafka access**, a real security boundary you can talk about):

| Tool | Backs onto | Returns |
|---|---|---|
| `get_user_history(user_id, hours)` | case-service internal API | recent txns + profile stats |
| `get_graph_neighborhood(user_id, depth≤2)` | stream-engine read API | nodes, edges, cycles, component size |
| `get_window_counts(user_id)` | stream-engine read API | live 1m/5m/1h aggregates |
| `find_similar_cases(summary_text, k=3)` | ChromaDB | past reports + outcomes |

### 6.2 The verify node — your evals story

Report schema forces citations:

```json
{ "summary": "...", "fraud_type": "RING|VELOCITY|GEO|MIXED|UNCERTAIN",
  "confidence": 0.82,
  "findings": [ {"claim": "...", "evidence_refs": [0, 3]} ],
  "recommended_action": "CONFIRM_BLOCK|RELEASE|ESCALATE" }
```

`verify` checks every `evidence_refs` index exists in `state.evidence` and that numbers quoted in claims appear in the referenced evidence payloads. Fail → one retry through `investigate`, then escalate with `UNCERTAIN`. **This is a hallucination guard implemented as code, not prompt-begging** — the single most differentiating thing in the project for AI Engineer interviews.

Embeddings: closed reports → `sentence-transformers all-MiniLM-L6-v2` → Chroma. Similar-case retrieval means the agent can say "matches case #12 (confirmed ring, 2 days ago)".

### 6.3 Agent eval harness

Because the generator knows ground truth, you get automatic agent evals: for each injected pattern, does the report's `fraud_type` match the injected type? How many tool calls did it need? Script: `evals/run.py` → accuracy per fraud type + mean tool calls → table in the README. Nobody has agent eval tables in portfolio projects; this is your differentiator.

---

## 7. Generator (Python)

- Poisson arrivals (~50 tps default) over ~500 synthetic users, each with a home city, favorite merchants, amount log-normal params, active hours.
- Injectors (each publishes the true label to `transactions.labels`):
  - `VelocityInjector`: pick a user, fire 15–40 txns in 1–3 min.
  - `RingInjector`: pick 4–8 accounts, send amounts around the cycle A→B→C→A over 10–30 min (tests edge TTL + cycle detection together).
  - `GeoInjector`: same card, two cities > 1000 km apart, minutes apart.
- CLI: `python -m generator --tps 50 --fraud-rate 0.02 --patterns ring,velocity,geo`
- Also the load-test tool: `--tps 2000 --fraud-rate 0` for the latency benchmark.

---

## 8. Dashboard (React, keep it thin)

Live ticker (WebSocket) with color-coded verdicts, cases table, case detail with the agent report + evidence, and a mini graph view of the user's neighborhood (`react-force-graph`, small). One evening of work, disproportionate demo value. No SSR, no auth, no state library — this is a window into the backend, not a product.

---

## 9. Config defaults (stream-engine `application.yml`)

```yaml
fraudgraph:
  velocity: { limit1m: 8, limit5m: 20, limit1h: 60 }
  geo:      { maxSpeedKmh: 900, minDistanceKm: 100, minGapSecs: 60 }
  graph:    { maxEdgesPerNode: 50, edgeTtlHours: 24, maxCycleDepth: 5 }
  scoring:  { timeoutMs: 150, sampleRate: 0.01,
              breaker: { window: 50, failureRate: 0.5, waitOpenSecs: 10 } }
  thresholds: { block: 0.85, review: 0.60, minSignalsForReview: 2 }
```

Every number here is an interview question ("why 900 km/h?") — keep a one-line justification comment next to each in the real file.

---

## 10. Testing & benchmarks

| Layer | Tool | What |
|---|---|---|
| Checks / rules / Welford / UnionFind / CycleDetector | JUnit 5 | pure-function tests, incl. edge cases (Δt=0, first txn, self-edge) |
| Topology | `TopologyTestDriver` | pipe crafted txns, assert decisions — no broker needed, runs in ms |
| Cross-service | Testcontainers (Kafka, Postgres) | generator→decision→case happy path + breaker-open path |
| Scorer | pytest | proto round-trip, feature parity test (same input → same vector in train & serve) |
| Agent | evals/run.py | fraud-type accuracy vs ground truth |
| Latency | generator `--tps 2000` + Micrometer timers | p50/p95/p99 per stage → README table |

The **feature-parity test** (train-side and serve-side `features.py` produce identical vectors for the same event) is the test most real ML systems lack — call it out.

---

## 11. Known limitations (write these in the README — honesty reads as seniority)

1. Graph is per-stream-thread, not global — rings split across partitions by different source users can be missed (fix: keyed co-partitioning of P2P edges or an external graph store).
2. Single-node Compose; Streams scales by partition count (6 → up to 6 instances) but the demo doesn't show it.
3. Thresholds hand-picked from one evaluation run; no online recalibration.
4. No feature store; profile features live only in stream state.

Each limitation + its fix is a prepared answer to "how would you scale this?"
