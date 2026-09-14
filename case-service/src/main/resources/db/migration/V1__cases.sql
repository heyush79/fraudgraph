-- LLD §5.1. gen_random_uuid() is built into Postgres 13+, no pgcrypto extension needed.
CREATE TABLE cases (
  case_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  txn_id       UUID NOT NULL UNIQUE,          -- idempotent case creation: one case per transaction
  user_id      TEXT NOT NULL,
  verdict      TEXT NOT NULL CHECK (verdict IN ('REVIEW','BLOCK')),
  ml_score     DOUBLE PRECISION,
  decision_doc JSONB NOT NULL,                -- the full fraud.decisions event, signals and all
  status       TEXT NOT NULL DEFAULT 'OPEN'
               CHECK (status IN ('OPEN','INVESTIGATING','REPORTED','CLOSED_FRAUD','CLOSED_FP')),
  report_doc   JSONB,                         -- analyst agent output, filled in Phase 5
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_cases_user   ON cases (user_id, created_at DESC);
CREATE INDEX idx_cases_status ON cases (status) WHERE status <> 'CLOSED_FP';
-- the dashboard's default view is "newest first across all statuses"
CREATE INDEX idx_cases_created ON cases (created_at DESC);

CREATE TABLE case_events (                    -- append-only audit trail per case
  id         BIGSERIAL PRIMARY KEY,
  case_id    UUID NOT NULL REFERENCES cases (case_id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,                   -- CREATED, AGENT_STARTED, REPORT_ATTACHED, STATUS_CHANGED
  payload    JSONB,
  at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_case_events_case ON case_events (case_id, at);
