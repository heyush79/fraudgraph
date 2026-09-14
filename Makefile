# FraudGraph — top-level developer commands (see CLAUDE.md).
#
#   make up      infra only (kafka, redis, postgres) — same as `docker compose up -d`
#   make demo    full stack + generator with fraud injection (+ dashboard from Phase 4)
#                GEN_TPS / GEN_FRAUD_RATE / GEN_PATTERNS / GEN_USERS / GEN_DURATION override the generator
#   make bench   latency benchmark: generator at high tps, no fraud
#   make train   train a new scorer version from fraud.decisions + transactions.labels and hot-reload it
#                TRAIN_HOURS=24 how far back to read;  make evaluate  prints the latest threshold sweep
#   make proto   regenerate gRPC code on both sides from proto/scoring.proto
#   make dash    dashboard in Vite dev mode against a locally running case-service
#   make evals   score the analyst agent against the generator's ground truth (EVAL_LIMIT=30)
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

.PHONY: up demo bench train train-local evaluate evals proto dash test test-java test-python down clean logs

up:
	$(COMPOSE) up -d

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

dash:
	cd dashboard && npm install && npm run dev

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
