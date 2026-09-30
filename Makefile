# FraudGraph — top-level developer commands (see CLAUDE.md).
#
#   make up      infra only (kafka, redis, postgres) — same as `docker compose up -d`
#   make lean    the pipeline only: kafka, postgres, redis, engine, case-service, generator.
#                No scorer (the engine degrades to rules, by design), no agent, no dashboard.
#                Roughly half the memory of `make demo`. Use this for day-to-day work.
#   make demo    full stack + generator with fraud injection (+ dashboard from Phase 4)
#                GEN_TPS / GEN_FRAUD_RATE / GEN_PATTERNS / GEN_USERS / GEN_DURATION override the generator
#   make bench   latency benchmark: generator at high tps, no fraud
#   make train   train a new scorer version from fraud.decisions + transactions.labels and hot-reload it
#                TRAIN_HOURS=24 how far back to read;  make evaluate  prints the latest threshold sweep
#   make proto   regenerate gRPC code on both sides from proto/scoring.proto
#   make dash    dashboard in Vite dev mode against a locally running case-service
#   make db-ui   browse Postgres at http://localhost:8080 (Adminer); make db-ui-stop to remove
#   make evals   score the analyst agent against the generator's ground truth (EVAL_LIMIT=30)
#   make scenario-ring | scenario-geo | scenario-velocity | scenario-policy
#                one labelled fraud episode now, compressed to a pace you can watch (needs `make demo`)
#                RING_ACCOUNTS=5 RING_GAP_SECS=15 shape the ring
#   make recall  what the running system actually caught per fraud pattern (RECALL_HOURS=1)
#   make share   a temporary public HTTPS URL for this stack (needs cloudflared); see deploy/README.md
#   make test    all unit tests (Java + Python), no broker needed
#   make down    stop everything, keep volumes;  make clean  also drops volumes

SHELL := /bin/bash
COMPOSE := docker compose

GEN_TPS        ?= 50
GEN_FRAUD_RATE ?= 0.02
GEN_PATTERNS   ?= velocity,ring,geo
GEN_USERS      ?= 20000
GEN_DURATION   ?=
TRAIN_HOURS    ?= 24
EVAL_LIMIT     ?= 30
EVAL_HOURS     ?= 6
RING_ACCOUNTS  ?= 5
RING_GAP_SECS  ?= 15
RECALL_HOURS   ?= 1

.PHONY: up lean demo bench train train-local evaluate evals recall proto dash db-ui db-ui-stop test test-java test-java-db test-python db-forget-migrations down clean logs \
	scenario-ring scenario-geo scenario-velocity scenario-policy share

up:
	$(COMPOSE) up -d

lean:
	GEN_TPS=$(GEN_TPS) GEN_FRAUD_RATE=$(GEN_FRAUD_RATE) GEN_PATTERNS=$(GEN_PATTERNS) \
	GEN_USERS=$(GEN_USERS) GEN_DURATION=$(GEN_DURATION) \
		$(COMPOSE) --profile core up -d
	@echo "engine: http://localhost:8081/actuator/health   cases: http://localhost:8082/cases"
	@echo "no scorer running, so flagged decisions will read mode=DEGRADED. That is the breaker working."

demo:
	GEN_TPS=$(GEN_TPS) GEN_FRAUD_RATE=$(GEN_FRAUD_RATE) GEN_PATTERNS=$(GEN_PATTERNS) \
	GEN_USERS=$(GEN_USERS) GEN_DURATION=$(GEN_DURATION) \
		$(COMPOSE) --profile demo up -d --build
	@echo "stream-engine actuator: http://localhost:8081/actuator/health"
	@echo "ml-scorer admin:        http://localhost:8000/health   (NO_MODEL until 'make train')"
	@echo "case-service API:       http://localhost:8082/cases"
	@echo "analyst-agent:          http://localhost:8010/health   (NO_MODEL until GROQ_API_KEY is set)"
	@echo "dashboard:              http://localhost:3000"
	@echo "decisions: docker exec fraudgraph-kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic fraud.decisions"

# Benchmark = generator on the host at high tps, zero fraud, fixed duration.
bench: up
	cd generator && uv run python -m generator --bootstrap-servers localhost:29092 \
		--tps 2000 --fraud-rate 0 --duration 60

# Runs inside the ml-scorer image on the compose network; writes ./ml-scorer/registry/vN and reloads the server.
train:
	$(COMPOSE) --profile demo run --rm --no-deps -e GIT_SHA=$$(git rev-parse --short HEAD 2>/dev/null || echo unknown) ml-scorer \
		python -m training.train --hours $(TRAIN_HOURS) --reload-url http://ml-scorer:8000/reload

# Same thing from the host (needs uv + libomp): reads localhost:29092, reloads localhost:8000.
train-local:
	cd ml-scorer && uv run python -m training.train --bootstrap-servers localhost:29092 --hours $(TRAIN_HOURS)

evaluate:
	cd ml-scorer && uv run python -m training.evaluate --registry registry

# Needs the stack up, a GROQ_API_KEY (or another provider) and some cases to work on.
evals:
	cd analyst-agent && uv run --extra dev python -m evals.run \
		--limit $(EVAL_LIMIT) --hours $(EVAL_HOURS) --agent-url http://localhost:8010

# Production recall, not offline recall: joins the verdicts the engine emitted to the labels.
# RECALL_SINCE=2026-09-29T16:24:30Z pins the window's start (a before/after comparison).
recall:
	cd ml-scorer && uv run python -m training.production_recall --hours $(RECALL_HOURS) $(if $(RECALL_SINCE),--since $(RECALL_SINCE))

# A one-off container from the generator image: the same population, Kafka address and code
# as the generator, without touching the one that is running.
SCENARIO := $(COMPOSE) --profile demo run --rm --no-deps -T --entrypoint python generator -m generator.scenario
scenario-ring:
	$(SCENARIO) ring --accounts $(RING_ACCOUNTS) --gap-secs $(RING_GAP_SECS)

scenario-geo scenario-velocity scenario-policy: scenario-%:
	$(SCENARIO) $*

# A public URL for the stack on this machine, for as long as the command runs (Ctrl-C closes it):
# read-only dashboard, rate-limited analyst, Cloudflare quick tunnel. `make demo` restores.
SHARE_ENV := $(if $(wildcard .env),--env-file .env) --env-file deploy/share.env
share:
	@command -v cloudflared >/dev/null || { echo "needs cloudflared: brew install cloudflared"; exit 1; }
	$(COMPOSE) -f docker-compose.yml -f deploy/docker-compose.share.yml $(SHARE_ENV) --profile demo \
		up -d --build dashboard analyst-agent
	@echo "sharing http://localhost:3000; the public URL appears below (…trycloudflare.com)"
	cloudflared tunnel --no-autoupdate --url http://localhost:3000

dash:
	cd dashboard && npm install && npm run dev

# Postgres is not HTTP, so a browser needs a client in front of it.
db-ui:
	$(COMPOSE) --profile tools up -d adminer
	@echo
	@echo "  http://localhost:8080"
	@echo "  system   PostgreSQL"
	@echo "  server   postgres      (the compose service name, not localhost)"
	@echo "  username fraudgraph"
	@echo "  password fraudgraph"
	@echo "  database fraudgraph"

db-ui-stop:
	$(COMPOSE) --profile tools rm -sf adminer

proto:
	cd ml-scorer && uv run python scripts/gen_proto.py
	cd stream-engine && mvn -q generate-sources

test: test-java test-python

# Testcontainers needs the Docker Desktop socket, which on macOS is under $$HOME rather than
# /var/run. Where the engine is too new for the bundled docker-java client the container-backed
# tests skip themselves rather than fail; see case-service/README.md.
test-java:
	cd stream-engine && mvn -q test
	cd case-service && DOCKER_HOST=$${DOCKER_HOST:-unix://$$HOME/.docker/run/docker.sock} mvn -q test

# The container-backed case-service tests against a database you start yourself. Use this
# where Testcontainers cannot reach the Docker engine (Docker Desktop 29), so the tests are
# debuggable locally instead of only ever running in CI.
# Migrations under case-service/src/main/resources/db/migration are IMMUTABLE once applied.
# Editing one changes its checksum and Flyway then refuses to start against every database
# that already ran it, which is an outage rather than a warning. Add a V2__ file instead.
# This target exists for the one case where you edited a migration by mistake on a demo
# database and just want to move on; it drops the recorded history so the next start
# re-validates from scratch. Never run it anywhere that matters.
db-forget-migrations:
	@echo "This drops flyway_schema_history. Only do this on a throwaway database."
	@read -p "type yes to continue: " ok && [ "$$ok" = "yes" ]
	docker exec fraudgraph-postgres psql -U fraudgraph -d fraudgraph \
		-c "DELETE FROM flyway_schema_history"
	$(COMPOSE) --profile demo restart case-service

test-java-db:
	docker rm -f fg-test-db >/dev/null 2>&1 || true
	docker run -d --name fg-test-db -e POSTGRES_USER=fraudgraph -e POSTGRES_PASSWORD=fraudgraph \
		-e POSTGRES_DB=fraudgraph -p 5433:5432 postgres:16-alpine >/dev/null
	@until docker exec fg-test-db pg_isready -U fraudgraph >/dev/null 2>&1; do sleep 1; done
	cd case-service && mvn -q test -Dfraudgraph.test.jdbcUrl=jdbc:postgresql://localhost:5433/fraudgraph; \
		status=$$?; docker rm -f fg-test-db >/dev/null 2>&1; exit $$status

test-python:
	cd generator && uv run --extra dev pytest -q
	cd ml-scorer && uv run --extra dev pytest -q
	cd analyst-agent && uv run --extra dev pytest -q

logs:
	$(COMPOSE) --profile demo logs -f --tail=100

down:
	$(COMPOSE) --profile demo down

clean:
	$(COMPOSE) --profile demo down -v
