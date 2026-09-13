# FraudGraph

Real-time payment fraud detection: a verdict per transaction (ALLOW / REVIEW / BLOCK) in under a second, and an evidence-cited analyst report for every flagged case.

Design docs: [CLAUDE.md](CLAUDE.md) (project memory) and [docs/fraudgraph-lld.md](docs/fraudgraph-lld.md) (low-level design).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | generator + Kafka + rules-only stream engine | done, demo verified |
| 2 | profile / geo state stores + in-memory graph checks | done |
| 3 | ML scorer, gRPC, circuit breaker | done |
| 4 | case service + dashboard | — |
| 5 | analyst agent + evals | — |

## Quick start

Prerequisites: Docker, JDK 17, Maven, Python 3.11+ with [uv](https://github.com/astral-sh/uv).

```bash
docker compose up -d          # kafka (KRaft, localhost:29092), redis, postgres; creates topics
make demo                     # + stream-engine + generator (velocity, ring, geo injection at 2%)
GEN_TPS=5 GEN_DURATION=300 make demo   # slower, stops after 5 minutes
make test                     # JUnit (TopologyTestDriver) + pytest, no broker needed
make train                    # after ~15 min of demo traffic: train v1 from the feature log, hot-reload the scorer
make evaluate                 # threshold sweep + per-pattern recall of the latest model
```

Scorer admin: `http://localhost:8000/health` (reports `NO_MODEL` until the first `make train`; the engine runs `mode: DEGRADED` meanwhile, by design).

Watch decisions:

```bash
docker exec fraudgraph-kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic fraud.decisions
```

Run pieces on the host instead of in Compose:

```bash
cd generator && uv run python -m generator --tps 50 --fraud-rate 0.02 --patterns velocity,ring,geo
cd generator && uv run python -m generator --dry-run --duration 5      # no Kafka, prints events
cd stream-engine && mvn spring-boot:run                                 # actuator on :8081
```

If `mvn` picks up a newer JDK, point it at 17: `export JAVA_HOME=$(/usr/libexec/java_home -v 17)`.

## What Phase 1 contains

- `docker-compose.yml`: single-broker KRaft Kafka with the four topics from LLD §2 created explicitly (6/3/6/1 partitions), Redis, Postgres. App services sit behind the `demo` profile.
- `generator/`: Poisson base traffic over 500 synthetic users, a `VelocityInjector` (15–40 txns in 1–3 min, paced to exceed the engine's per-minute limit), ground truth on `transactions.labels`. Ring and geo injectors arrive with Phase 2.
- `stream-engine/`: Kafka Streams Processor API topology `dedup → enrich → check → decision`, with the `dedup-store` and the three velocity window stores (`velocity-1m/5m/1h`, bucketed sliding windows), `VelocityCheck`, hard-block rules (sanctioned merchant, amount cap), the LLD §3.6 threshold policy, a `DegradedScoringClient` standing in for the Phase 3 gRPC scorer, DLQ routing for poison messages and decision failures, `exactly_once_v2`.
- `proto/scoring.proto`: the feature-vector contract; the engine's `FeatureVector` mirrors it by hand until Phase 3 codegen.

## What Phase 2 added

- **Generator**: 20,000 users with small P2P contact circles; `RingInjector` (4–8 accounts pass a shrinking amount around a cycle over 10–30 min) and `GeoInjector` (one anchor at home, then 1–3 cloned-card transactions from a city over 1,000 km away, minutes later).
- **Engine**: `profile-store` (Welford rolling mean/std → `amtZ`, trusted after 10 samples), `last-location-store` → `GeoCheck` (haversine, fires above 900 km/h *and* 100 km, skips gaps under 60 s), and the in-memory `TransactionGraph` (≤ 50 edges per node, 24 h TTL, union-find components, bounded DFS to depth 5) → `GraphCheck` firing `RING_SUSPECT` with the cycle as evidence. Decisions now carry `signals` with evidence and an honest end-to-end `latencyMs`.

## What Phase 3 added

- **ml-scorer/** (Python 3.12): gRPC scoring server (`grpc.aio`, 4 worker threads) + FastAPI admin (`/health`, `/model`, `/reload?version=vN`, `/metrics`) in one process. `scorer/features.py` is the one place feature order and encoding live, derived from the proto descriptor; the serving path (proto) and the training path (the `features` map on `fraud.decisions`) go through it, and `tests/test_features_parity.py` asserts they agree. XGBoost with `scale_pos_weight` for the ~2% positive rate; TreeSHAP top-5 contributions via XGBoost's native `pred_contribs`, computed only when probability ≥ 0.4. Model registry `registry/vN/{model.json, meta.json, metrics.json, data.parquet}`.
- **Training** reads the last N hours of `fraud.decisions` (seeking by timestamp) and `transactions.labels`, joins on `txnId`, splits **by time** (first 80% trains, last 20% tests), sweeps thresholds, reports per-pattern recall, writes a new registry version and hot-reloads the server. `make train` runs it in the compose network.
- **Engine**: Java classes generated from `proto/scoring.proto` at build time; `GrpcScoringClient` with a 150 ms deadline wrapped in `ResilientScoringClient` (Resilience4j count-based breaker: window 50, opens at 50% failure after 10 calls, half-open after 10 s). Open breaker or any failure → `ScoreResult.degraded()` → `mode: DEGRADED`, never an exception on the stream. Breaker state, transitions, call outcomes and scorer latency are all Micrometer metrics.
- **Drift guards**: `FeatureVectorProtoParityTest` (Java) pins the record, its JSON keys and the proto to each other; `test_features_parity.py` (Python) pins the feature list to the proto descriptor and train rows to serve rows.

## Model v1 (trained 2026-09-12 on 1.64 M logged decisions, 2.01% fraud)

Time split: first 80% trains, last 20% (~1.8 h) tests. PR-AUC 0.973, ROC-AUC 0.998. Full sweep: `make evaluate`.

| threshold | precision | recall | F1 | flagged rate |
|---|---|---|---|---|
| 0.60 (review) | 0.702 | 0.975 | 0.817 | 2.72% |
| 0.85 | 0.845 | 0.955 | 0.897 | 2.21% |
| 0.95 (block) | 0.926 | 0.924 | 0.925 | 1.96% |

Recall per injected pattern at 0.95: geo 0.867, ring 0.991, velocity 0.908. Top features by gain: `cnt_1m`, `merchant_risk_tier`, `amt_z`, `secs_since_last`, `geo_speed_kmh`. No threshold reaches 98% precision, so auto-block sits at 0.95 rather than the LLD's 0.85 placeholder. Two honest caveats: ring recall is high because the ring injector's amounts (₹20k–80k P2P) are far outside normal spend, so `amt_z` and `channel` catch rings without the graph feature (`in_cycle` ranks last by gain); and `merchant_risk_tier` ranks second because the injectors favour high-tier merchants. Both are generator realism issues, listed under limitations.

## Known limitations

See LLD §11. The ring injector's amounts make rings separable by amount alone, so the v1 model does not need `in_cycle`; making ring hops look like ordinary P2P transfers (amounts from the users' own spend distribution) is the next generator change, and the graph feature will only prove its worth after it. Until the first `make train`, every flagged decision is `mode: DEGRADED` (the breaker sees `FAILED_PRECONDITION` from the model-less scorer), so signals produce REVIEW, never BLOCK, unless a hard rule fires. The engine's `thresholds.block` (0.95) and `review` (0.60) were read off the v1 sweep table (precision 0.926 / 0.70, recall 0.924 / 0.975); rerun `make train` and `make evaluate` and revisit them when the model or the traffic changes. The graph is per engine instance and not persisted; after a restart it warms back up within the 24 h edge TTL. After a geo episode the real cardholder's next purchase at home can also trip `GEO_IMPOSSIBLE`, which is faithful to reality but counts as a false positive against the generator's labels.
