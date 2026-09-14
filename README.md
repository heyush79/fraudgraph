# FraudGraph

[![CI](https://github.com/heyush79/fraudgraph/actions/workflows/ci.yml/badge.svg)](https://github.com/heyush79/fraudgraph/actions/workflows/ci.yml)


Real-time payment fraud detection: a verdict per transaction (ALLOW / REVIEW / BLOCK) in under a second, and an evidence-cited analyst report for every flagged case.

Design docs: [CLAUDE.md](CLAUDE.md) (project memory) and [docs/fraudgraph-lld.md](docs/fraudgraph-lld.md) (low-level design).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | generator + Kafka + rules-only stream engine | done, demo verified |
| 2 | profile / geo state stores + in-memory graph checks | done |
| 3 | ML scorer, gRPC, circuit breaker | done |
| 4 | case service + dashboard | done |
| 5 | analyst agent + evals | done |

## Quick start

Prerequisites: Docker, JDK 17, Maven, Python 3.11+ with [uv](https://github.com/astral-sh/uv).

```bash
docker compose up -d          # kafka (KRaft, localhost:29092), redis, postgres; creates topics
make demo                     # + stream-engine + generator (velocity, ring, geo injection at 2%)
GEN_TPS=5 GEN_DURATION=300 make demo   # slower, stops after 5 minutes
make test                     # all 163 tests: JUnit + pytest, no broker and no API key needed
make train                    # after ~15 min of demo traffic: train v1 from the feature log, hot-reload the scorer
make evaluate                 # threshold sweep + per-pattern recall of the latest model
```

Dashboard: `http://localhost:3000`. Case API: `http://localhost:8082/cases`. Scorer admin: `http://localhost:8000/health` (reports `NO_MODEL` until the first `make train`; the engine runs `mode: DEGRADED` meanwhile, by design).

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

**IDE showing unresolved imports?** Both sides of the gRPC contract are generated from `proto/scoring.proto` at build time and are not checked in, so a fresh clone has no `com.fraudgraph.scoring.v1` (Java) and no `scorer.gen` (Python) until something generates them. Run `make proto`, then reload the project in your IDE. The Java source roots are declared with `build-helper-maven-plugin` so any IDE that reads the POM picks them up; before that was added, VS Code flagged `GrpcScoringClient` and the two scoring tests as broken while `mvn test` was green.

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

## Model v2 (trained 2026-09-14 on 277k logged decisions, 2.16% fraud)

The first model trained after ring amounts were drawn from each account's own spending rather than a flat band. Time split: first 80% trains, last 20% tests. Full sweep: `make evaluate`.

| threshold | precision | recall | F1 | flagged rate |
|---|---|---|---|---|
| 0.60 (review) | 0.564 | 0.874 | 0.685 | 3.80% |
| 0.95 | 0.922 | 0.699 | 0.795 | 1.86% |
| 0.99 (block) | 0.985 | 0.573 | 0.724 | 1.43% |

**Making the generator honest cost the model a third of its apparent quality, which is the point.** PR-AUC fell from 0.973 to 0.873 and ring recall collapsed from 99% to 44%. v1 was not good at finding rings; it was good at finding transfers of ₹20,000–80,000, because that was the only amount band the ring injector ever used. Once ring hops look like the accounts' own spending, the model has to actually use the graph, and `in_cycle` rose from last of twelve features by gain to ninth, above three of the velocity counts.

Recall per injected pattern at the review threshold: velocity 0.889, geo 0.733, ring 0.437. Ring remains the hardest by a distance, and the reason is structural rather than statistical: only the hop that *closes* a cycle carries `in_cycle`, so the other four to seven hops of a ring are, to the model, ordinary peer-to-peer transfers. A "member of a recently closed cycle" feature is the obvious next step.

Top features by gain: `merchant_risk_tier`, `cnt_1m`, `channel`, `amt_z`, `secs_since_last`. Merchant tier ranking first is still partly an artifact of the injectors favouring high-tier merchants.

## Known limitations

See LLD §11. The agent runs on a free tier, so `make evals` throttles between cases and a full run takes tens of minutes; the eval numbers are for a mid-tier open model, not a frontier one, which is also why the verify node fires often enough to be worth watching. The case-service Testcontainers test skips on Docker Desktop 29, whose engine API the bundled docker-java client cannot negotiate; it runs on a standard Linux socket, and the idempotency it covers was verified against the live stack instead. The ring injector's amounts make rings separable by amount alone, so the v1 model does not need `in_cycle`; making ring hops look like ordinary P2P transfers (amounts from the users' own spend distribution) is the next generator change, and the graph feature will only prove its worth after it. Until the first `make train`, every flagged decision is `mode: DEGRADED` (the breaker sees `FAILED_PRECONDITION` from the model-less scorer), so signals produce REVIEW, never BLOCK, unless a hard rule fires. The engine's `thresholds.block` (0.95) and `review` (0.60) were read off the v1 sweep table (precision 0.926 / 0.70, recall 0.924 / 0.975); rerun `make train` and `make evaluate` and revisit them when the model or the traffic changes. The graph is per engine instance and not persisted; after a restart it warms back up within the 24 h edge TTL. After a geo episode the real cardholder's next purchase at home can also trip `GEO_IMPOSSIBLE`, which is faithful to reality but counts as a false positive against the generator's labels.
