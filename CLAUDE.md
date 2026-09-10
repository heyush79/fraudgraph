# FraudGraph — project memory

## What this is
Real-time payment fraud detection pipeline. Portfolio project targeting both backend (Java) and AI Engineer roles. Verdict per transaction (ALLOW / REVIEW / BLOCK) in <1s, every flagged case gets an evidence-cited analyst report.

**The full LLD is at `docs/fraudgraph-lld.md` — read it before designing or changing any component.** It pins down Kafka topics, state stores, the gRPC proto, DB schema, algorithms, and config defaults. Do not contradict it silently; if a decision there seems wrong, raise it and propose a change first.

## Architecture in one paragraph
Python generator → Kafka `transactions.raw` (keyed by userId, 6 partitions) → Java Kafka Streams engine (dedup → enrich → checks: velocity windows / geo impossible-travel / in-memory graph ring detection → decision) → gRPC call to Python ML scorer (XGBoost + SHAP) only when signals fire → `fraud.decisions` → Spring Boot case service (Postgres) → LangGraph analyst agent writes cited reports → React dashboard over WebSocket.

## Monorepo layout
- `generator/` — Python, traffic + fraud injectors (velocity, ring, geo), publishes ground truth to `transactions.labels`
- `stream-engine/` — Java 17, Spring Boot 3, Kafka Streams (Processor API for check/decision stages)
- `ml-scorer/` — Python, gRPC serving + FastAPI admin, training pipeline in `training/`
- `case-service/` — Java 17, Spring Boot 3, Postgres, WebSocket feed
- `analyst-agent/` — Python, LangGraph + ChromaDB
- `dashboard/` — React (Vite), intentionally thin
- `proto/scoring.proto` — single source of truth for the feature vector; Java AND Python codegen from it

## Non-negotiable design decisions (from the LLD — do not "improve" these without asking)
- Hot-path state lives in Kafka Streams state stores (RocksDB + changelogs), NOT Redis. Redis is only for cross-service reads.
- Transaction graph is in-memory (bounded DFS depth ≤5, ≤50 edges/node, 24h edge TTL, union-find for components). No Neo4j in v1.
- ML scorer is called synchronously with a 150ms timeout behind a Resilience4j circuit breaker; open breaker → rules-only DEGRADED mode, never stall the stream.
- LLM/agent is NEVER on the decisioning hot path — it runs async after a case is created.
- Agent reports must cite evidence: the `verify` node programmatically checks every claim's evidence_refs. Keep this guard; it is the point of the project.
- Training data split by TIME, never randomly.
- Exactly-once (`processing.guarantee=exactly_once_v2`) + txnId dedup store; case creation idempotent via `UNIQUE(txn_id)` + ON CONFLICT DO NOTHING.

## Conventions
- Java: 17, records for models, constructor injection, no Lombok. Checks are pure functions that never throw (log + return empty).
- Python: 3.11+, type hints everywhere, pytest.
- Config: all thresholds in `stream-engine` `application.yml` under `fraudgraph:`; every number gets a one-line justification comment.
- Tests: JUnit 5 + TopologyTestDriver for the stream engine; Testcontainers for integration; feature-parity test (train vs serve vectors identical) is mandatory and must never be deleted.
- Commits: small, per-component, imperative mood.

## Commands
- `docker compose up -d` — kafka, redis, postgres
- `make demo` — full stack + generator with fraud injection + dashboard
- `make train` — retrain scorer from labeled topics
- `make bench` — latency benchmark (generator at high tps, no fraud)

## Current status
<!-- keep this section updated as you build -->
- [x] Phase 1: generator + Kafka + rules-only stream engine (scaffolded 2026-09-11; velocity windows + dedup store live here, profile/geo/graph stores in Phase 2)
- [ ] Phase 2: state stores (windows, profiles, geo) + graph checks
- [ ] Phase 3: ML scorer + gRPC + circuit breaker
- [ ] Phase 4: case service + dashboard
- [ ] Phase 5: analyst agent + evals
