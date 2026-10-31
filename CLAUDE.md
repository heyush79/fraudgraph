# FraudGraph — project memory

## What this is
Real-time payment fraud detection pipeline. Portfolio project targeting both backend (Java) and AI Engineer roles. Verdict per transaction (ALLOW / REVIEW / BLOCK) in <1s, every flagged case gets an evidence-cited analyst report.
Stack: Java 17 + Spring Boot 3.3.5 + Kafka Streams (broker `apache/kafka:3.8.1`, KRaft); Python 3.11+ (ml-scorer and analyst-agent pinned to 3.12) with XGBoost, gRPC, FastAPI, LangGraph, ChromaDB; Postgres 16, Redis 7; React 19 + Vite 8 + TypeScript 5.9.

**The full LLD is at `docs/fraudgraph-lld.md` — read it before designing or changing any component.** It pins down Kafka topics, state stores, the gRPC proto, DB schema, algorithms, and config defaults. Do not contradict it silently; if a decision there seems wrong, raise it and propose a change first.

## How to run it
Tools: JDK 17 + Maven 3.9 (no wrapper), uv, Node (CI: 22). Maven uses `JAVA_HOME`, not the `java` on PATH: point it at JDK 17 (see Known issues), e.g. `export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home`. `uv run` makes a gitignored `.venv/` per module. Timings: run on 2026-11-01, Apple Silicon, warm caches.
- `make test` — stream-engine, case-service, generator, ml-scorer, analyst-agent; no broker, no API key. ~50s. Skips showcase (CI runs it) and dashboard.
- Per module, as CI runs it (`.github/workflows/ci.yml`), from the module dir:
  - `stream-engine/`: `mvn -B -ntp test` — 78 pass, ~20–40s; protoc codegen runs inside the build.
  - `case-service/`: `mvn -B -ntp test` — 13 pass, 7 skip (`CaseRepositoryTest`, needs Docker), ~5s.
  - `generator/`: `uv run --extra dev pytest -q` — 32 pass, ~5s.
  - `ml-scorer/`: `uv run python scripts/gen_proto.py && uv run --extra dev pytest -q` — 38 pass, ~35s first run (deps), ~7s after.
  - `analyst-agent/`: `uv run --extra dev pytest -q` — 118 pass, ~5s; CI sets `GROQ_API_KEY=''`.
  - `showcase/`: `uv run --extra dev pytest -q` — 10 pass, ~2s.
  - `dashboard/`: `npm ci && npm run build` (`tsc --noEmit && vite build`) — ~5s.
- Single test: `cd stream-engine && mvn -B -ntp test -Dtest=GeoCheckTest` (~3s); `cd ml-scorer && uv run --extra dev pytest -q tests/test_features_parity.py`; by name: `uv run --extra dev pytest -q -k unknown_case` (analyst-agent). case-service DB tests on a throwaway Postgres: `make test-java-db` (needs Docker; not verified).
- Lint/format: none configured (no ruff, black, eslint, prettier or checkstyle; CI does not lint). Only static check: `npm run typecheck` in `dashboard/`. Match the surrounding style.
- Proto codegen: `make proto` (Python `ml-scorer/scorer/gen/` + `mvn -q generate-sources`). Generated code is not committed: Java lands in `stream-engine/target/generated-sources/protobuf/` on every build; `scorer/gen/` is gitignored.

Stack commands (need Docker or a running stack; not run while writing this, unverified):
- `docker compose up -d` — kafka, redis, postgres
- `make dash` — dashboard in Vite dev mode against a local case-service
- `make demo` — full stack + generator with fraud injection + dashboard
- `make train` — train a scorer version from fraud.decisions + transactions.labels (TRAIN_HOURS=24) and hot-reload it; `make evaluate` prints the threshold sweep
- `make bench` — latency benchmark (generator at high tps, no fraud)
- `make evals` — score the analyst agent against the generator's ground truth (needs `GROQ_API_KEY`)
- `make recall` — production recall per fraud pattern from the live verdicts (`RECALL_SINCE=<iso>` pins the window)
- `make scenario-ring|geo|velocity|policy` — one labelled episode now, compressed to watchable pace
- `make share` — temporary public HTTPS URL for the local stack (cloudflared; read-only, rate-limited)
- `uv run python record.py` in `showcase/` — record a live session into `dashboard/public/showcase/` for the replay site
- Also: `make up` (= `docker compose up -d`), `make lean` (pipeline only, no scorer/agent/dashboard, ~half the memory), `make train-local` (host, needs libomp), `make logs`, `make db-ui` (Adminer :8080), `make down` (keep volumes), `make clean` (drop volumes).

Env vars: tests need none. Compose reads a repo-root `.env` (gitignored, no example file): `GROQ_API_KEY`, optional `FRAUDGRAPH_LLM_PROVIDER` (groq|ollama|gemini), `FRAUDGRAPH_LLM_MODEL`, `GOOGLE_API_KEY`, `OLLAMA_BASE_URL`, `FRAUDGRAPH_BIND`, `FRAUDGRAPH_ASK_RATE_*`. Examples: `deploy/public.env.example` (copy to gitignored `deploy/public.env`), `deploy/share.env`, `dashboard/.env.example` (`VITE_*`). Service defaults: `FRAUDGRAPH_*` in each `application.yml` and `analyst-agent/agent/settings.py`, `SCORER_*` in `ml-scorer/scorer/settings.py`. Make knobs: `GEN_TPS GEN_FRAUD_RATE GEN_PATTERNS GEN_USERS GEN_DURATION TRAIN_HOURS EVAL_LIMIT EVAL_HOURS RING_ACCOUNTS RING_GAP_SECS RECALL_HOURS RECALL_SINCE`. Host ports: kafka 29092, postgres 5432, redis 6379, engine 8081, cases 8082, scorer gRPC 50051 + admin 8000, agent 8010, dashboard 3000 (Vite dev 5173).

## Project layout
- `generator/` — Python, traffic + fraud injectors (velocity, ring, geo), publishes ground truth to `transactions.labels`
- `stream-engine/` — Java 17, Spring Boot 3, Kafka Streams (Processor API for check/decision stages)
- `ml-scorer/` — Python, gRPC serving + FastAPI admin, training pipeline in `training/`; served models in `registry/`
- `case-service/` — Java 17, Spring Boot 3, Postgres, WebSocket feed
- `analyst-agent/` — Python, LangGraph + ChromaDB
- `dashboard/` — React (Vite); the public console, `live` or `replay` data mode (contract: `docs/showcase-contract.md`)
- `showcase/` — Python, records a live session into the static replay the GitHub Pages site plays
- `deploy/` — public deployment: compose overlay + Caddy for a free VM, `make share` tunnel settings
- `proto/scoring.proto` — single source of truth for the feature vector; Java AND Python codegen from it
- `Makefile`, `docker-compose.yml` (profiles `core`, `demo`, `tools`), `.github/workflows/` (`ci.yml`: 8 jobs + one `all green` check; `pages.yml`: replay site)

## Architecture in short
- Python generator → Kafka `transactions.raw` (keyed by userId, 6 partitions) — `generator/generator/publisher.py`
- → Java Kafka Streams engine (dedup → enrich → checks: velocity windows / geo impossible-travel / in-memory graph ring detection → decision) — `stream-engine/.../config/TopologyBuilder.java`, `processor/`, `check/`, `graph/`
- → gRPC call to Python ML scorer (XGBoost + SHAP) only when signals fire (plus a 1% sample, `scoring.sampleRate`) — `scoring/ResilientScoringClient.java` → `ml-scorer/scorer/server.py`
- → `fraud.decisions` (failures → `transactions.dlq`) → Spring Boot case service (Postgres) — `case-service/.../kafka/DecisionConsumer.java`, `store/CaseRepository.java`
- → LangGraph analyst agent writes cited reports — `analyst-agent/agent/graph.py` (triage → investigate → similar_cases → draft_report → verify → finalize), `agent/verify.py`
- → React dashboard over WebSocket — case-service `/ws/feed`, `dashboard/src/data/live.ts`
- Training: `ml-scorer/training/train.py` joins `fraud.decisions` + `transactions.labels`, writes `ml-scorer/registry/vN`

## Conventions
- Java: 17, records for models, constructor injection, no Lombok. Checks are pure functions that never throw (log + return empty).
- Python: 3.11+, type hints everywhere, pytest.
- Config: all thresholds in `stream-engine` `application.yml` under `fraudgraph:`; every number gets a one-line justification comment.
- Tests: JUnit 5 + TopologyTestDriver for the stream engine; Testcontainers for integration; feature-parity test (train vs serve vectors identical) is mandatory and must never be deleted.
- Commits: small, per-component, imperative mood. Subjects in git log are sentence case with no type prefix (e.g. `Fix two timing-sensitive tests that would flake on CI`).
- Errors: checks/rules catch `RuntimeException`, `log.warn`, return empty; poison records → `transactions.dlq`; scorer failure → `mode: DEGRADED`, never an exception on the stream.
- Logging: Java SLF4J `private static final Logger log`; Python `log = logging.getLogger(__name__)`; `print` only for CLI output.
- Test style: AssertJ, behaviour-sentence names (`firstTransactionHasNoPriorLocation`, `test_an_unknown_case_is_404`); `asyncio_mode = "auto"`; analyst-agent mocks HTTP with respx and replays a scripted model.
- Python settings are a frozen `Settings` dataclass reading env vars with defaults; comments explain why, not what.

## Do NOT
Non-negotiable design decisions (from the LLD — do not "improve" these without asking):
- Hot-path state lives in Kafka Streams state stores (RocksDB + changelogs), NOT Redis. Redis is only for cross-service reads.
- Transaction graph is in-memory (bounded DFS depth ≤5, ≤50 edges/node, 24h edge TTL, union-find for components). No Neo4j in v1.
- ML scorer is called synchronously with a 150ms timeout behind a Resilience4j circuit breaker; open breaker → rules-only DEGRADED mode, never stall the stream.
- LLM/agent is NEVER on the decisioning hot path — it runs async after a case is created. Not on the case-creation path either: the hand-off is fire-and-forget behind a bounded retry queue.
- The agent reads ONLY through case-service `/internal/*`. No DB handle, no Kafka client, no state-store access. Do not add one.
- Agent reports must cite evidence: the `verify` node programmatically checks every claim's evidence_refs. Keep this guard; it is the point of the project.
- Training data split by TIME, never randomly.
- Exactly-once (`processing.guarantee=exactly_once_v2`) + txnId dedup store; case creation idempotent via `UNIQUE(txn_id)` + ON CONFLICT DO NOTHING.

Repo rules:
- Hand-edit or commit generated proto code. Edit `proto/scoring.proto` and run `make proto`. Field numbers only grow (LLD §4.1); update the Java `FeatureVector` record too. Never delete or weaken `ml-scorer/tests/test_features_parity.py` or `stream-engine/.../scoring/FeatureVectorProtoParityTest.java`.
- Edit an applied Flyway migration (`case-service/src/main/resources/db/migration/V1__cases.sql`). Flyway refuses to start on a checksum change; add `V2__...` instead.
- Add case-service tests that skip. CI fails that job if any surefire report has skipped > 0.
- Commit `.env` or `deploy/public.env` (they hold the model key). Tests must pass with no provider key.
- Delete `ml-scorer/registry/v3/` (the shipped model) or `_rejected-v2-tiny-window/` (kept on purpose, see its `WHY_REJECTED.md`).
- Hand-edit `dashboard/public/showcase/`. `showcase/record.py` writes it, and Pages refuses to deploy without its `manifest.json`.
- Change `.github/workflows/`, `deploy/` or compose `mem_limit`s as a side effect of other work.

## Gotchas
- `ml-scorer/tests/conftest.py` generates `scorer/gen/` only if it is missing: after a proto change rerun `scripts/gen_proto.py` or tests use stale stubs.
- stream-engine and ml-scorer read `../proto`, so their Docker build context is the repo root; the other images build from their module dir.
- generator/ and showcase/ have no `.python-version`; uv picked CPython 3.14 on the dev Mac and tests passed. ml-scorer/analyst-agent need `<3.13`.
- XGBoost needs OpenMP: `libomp` on macOS, `libgomp1` on Linux (CI installs it).
- `CaseRepositoryTest` skips (not fails) with no reachable Docker, and on Docker Desktop 29 (docker-java cannot negotiate its API). Override: `-Dfraudgraph.test.jdbcUrl=...`. The Makefile cites `case-service/README.md`, which does not exist; the explanation is in the test's javadoc.
- On the host, ml-scorer admin and analyst-agent both default to :8000 (compose maps the agent to 8010). case-service defaults to agent hand-off off and `FRAUDGRAPH_AGENT_URL=http://localhost:8000` (the scorer admin port).
- stream-engine source and case-service consumer start at `latest` on first start; earlier events are never processed. Kafka auto-create is off: topics come from `kafka-init` in `docker-compose.yml`.
- Thresholds moved after LLD §9 (block 0.85) and BUILD_HISTORY (0.95); current values and reasons are in `stream-engine/src/main/resources/application.yml` (block 0.99, review 0.60).
- The scorer serves the highest `registry/vN` that has `model.json` + `meta.json`; `make train` writes v4+ (gitignored). The `make demo` banner "NO_MODEL until 'make train'" predates shipping v3.

## Known issues
- case-service tests fail when Maven runs on JDK 26 (e.g. `JAVA_HOME` left at a newer JDK; `make test` then fails): 7 errors in `FeedBroadcasterTest`, "Mockito cannot mock this class: interface org.springframework.web.socket.WebSocketSession", caused by "Java 26 (70) is not supported by the current version of Byte Buddy which officially supports Java 23 (67)". Passes on JDK 17. stream-engine passes on both.
- Needs Docker (not verified): `CaseRepositoryTest` (7 tests), `make test-java-db`, the CI `images` job, all compose/`make demo`-type targets.

## Where things are documented
- `docs/fraudgraph-lld.md` — topics, stores, proto, schema, algorithms, config, test plan; §11 known limitations
- `docs/DESIGN.md` — decisions, tradeoffs, numbers, what is not done; `docs/showcase-contract.md` — dashboard data modes, ask endpoint, replay format
- `docs/BUILD_HISTORY.md` (phase history, model v2 sweep); `docs/blog/ring-recall.md`; `docs/demo-video-script.md`
- Module READMEs: `analyst-agent/`, `dashboard/`, `deploy/`, `showcase/` (none for the Java modules, generator or ml-scorer)

## Current status / next steps
<!-- keep this section updated as you build -->
- [x] Phase 1: generator + Kafka + rules-only stream engine (scaffolded 2026-09-11; velocity windows + dedup store live here, profile/geo/graph stores in Phase 2)
- [x] Phase 2: state stores (profiles, geo) + graph checks + ring/geo injectors (2026-09-12)
- [x] Phase 3: ML scorer + gRPC + circuit breaker (2026-09-12; trains from the fraud.decisions feature log, see LLD §4.3 amendment)
- [x] Phase 4: case service + dashboard (2026-09-13; engine gained a /read API, Redis holds per-user recent decisions)
- [x] Phase 5: analyst agent + evals (2026-09-14; runs on Groq's free tier, provider is one env var)
- [x] Showcase (2026-09-29 – 09-30): PASS_THROUGH signal + features (production ring recall 7.2% → 84.5%, LLD §3.5), model v3 served by feature name and shipped in `ml-scorer/registry/v3`, "ask the analyst" endpoint with sentence-level verification, verifier tightened (LLD §6.2), scenarios, recorder, GitHub Pages replay, `deploy/`. Design doc: `docs/DESIGN.md`. Open items: LLD §11 items 5–9.
