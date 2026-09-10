# FraudGraph

Real-time payment fraud detection: a verdict per transaction (ALLOW / REVIEW / BLOCK) in under a second, and an evidence-cited analyst report for every flagged case.

Design docs: [CLAUDE.md](CLAUDE.md) (project memory) and [docs/fraudgraph-lld.md](docs/fraudgraph-lld.md) (low-level design).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | generator + Kafka + rules-only stream engine | scaffolded, unit-tested |
| 2 | profile / geo state stores + in-memory graph checks | — |
| 3 | ML scorer, gRPC, circuit breaker | — |
| 4 | case service + dashboard | — |
| 5 | analyst agent + evals | — |

## Quick start

Prerequisites: Docker, JDK 17, Maven, Python 3.11+ with [uv](https://github.com/astral-sh/uv).

```bash
docker compose up -d          # kafka (KRaft, localhost:29092), redis, postgres; creates topics
make demo                     # + stream-engine + generator (velocity injection at 2%)
make test                     # JUnit (TopologyTestDriver) + pytest, no broker needed
```

Watch decisions:

```bash
docker exec fraudgraph-kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic fraud.decisions
```

Run pieces on the host instead of in Compose:

```bash
cd generator && uv run python -m generator --tps 50 --fraud-rate 0.02 --patterns velocity
cd generator && uv run python -m generator --dry-run --duration 5      # no Kafka, prints events
cd stream-engine && mvn spring-boot:run                                 # actuator on :8081
```

If `mvn` picks up a newer JDK, point it at 17: `export JAVA_HOME=$(/usr/libexec/java_home -v 17)`.

## What Phase 1 contains

- `docker-compose.yml`: single-broker KRaft Kafka with the four topics from LLD §2 created explicitly (6/3/6/1 partitions), Redis, Postgres. App services sit behind the `demo` profile.
- `generator/`: Poisson base traffic over 500 synthetic users, a `VelocityInjector` (15–40 txns in 1–3 min, paced to exceed the engine's per-minute limit), ground truth on `transactions.labels`. Ring and geo injectors arrive with Phase 2.
- `stream-engine/`: Kafka Streams Processor API topology `dedup → enrich → check → decision`, with the `dedup-store` and the three velocity window stores (`velocity-1m/5m/1h`, bucketed sliding windows), `VelocityCheck`, hard-block rules (sanctioned merchant, amount cap), the LLD §3.6 threshold policy, a `DegradedScoringClient` standing in for the Phase 3 gRPC scorer, DLQ routing for poison messages and decision failures, `exactly_once_v2`.
- `proto/scoring.proto`: the feature-vector contract; the engine's `FeatureVector` mirrors it by hand until Phase 3 codegen.

## Known limitations

See LLD §11. Additionally in Phase 1: every scored decision is `mode: DEGRADED` because there is no scorer yet, so signals produce REVIEW, never BLOCK, unless a hard rule fires.
