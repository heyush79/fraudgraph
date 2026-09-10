# FraudGraph — top-level developer commands (see CLAUDE.md).
#
#   make up      infra only (kafka, redis, postgres) — same as `docker compose up -d`
#   make demo    full stack + generator with fraud injection (+ dashboard from Phase 4)
#   make bench   latency benchmark: generator at high tps, no fraud
#   make train   retrain the ML scorer from labeled topics (Phase 3)
#   make test    all unit tests (Java + Python), no broker needed
#   make down    stop everything, keep volumes;  make clean  also drops volumes

SHELL := /bin/bash
COMPOSE := docker compose

GEN_TPS        ?= 50
GEN_FRAUD_RATE ?= 0.02
GEN_PATTERNS   ?= velocity

.PHONY: up demo bench train test test-java test-python down clean logs

up:
	$(COMPOSE) up -d

demo:
	GEN_TPS=$(GEN_TPS) GEN_FRAUD_RATE=$(GEN_FRAUD_RATE) GEN_PATTERNS=$(GEN_PATTERNS) \
		$(COMPOSE) --profile demo up -d --build
	@echo "stream-engine actuator: http://localhost:8081/actuator/health"
	@echo "decisions: docker exec fraudgraph-kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic fraud.decisions"

# Benchmark = generator on the host at high tps, zero fraud, fixed duration.
bench: up
	cd generator && uv run python -m generator --bootstrap-servers localhost:29092 \
		--tps 2000 --fraud-rate 0 --duration 60

train:
	@echo "ml-scorer arrives in Phase 3 (make train will run ml-scorer/training/train.py)"; exit 1

test: test-java test-python

test-java:
	cd stream-engine && mvn -q test

test-python:
	cd generator && uv run --extra dev pytest -q

logs:
	$(COMPOSE) --profile demo logs -f --tail=100

down:
	$(COMPOSE) --profile demo down

clean:
	$(COMPOSE) --profile demo down -v
