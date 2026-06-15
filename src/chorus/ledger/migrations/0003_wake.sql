-- Migration 0003 — wake (spec 01 Cluster C): the coalescing push inbox.
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Declarative copy lives in ../schema/wake.sql; test_schema_parity asserts they agree.

CREATE TABLE wake (
    id              TEXT PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employee(id),
    reason          TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'queued',
    coalesce_key    TEXT NOT NULL,
    coalesced_count INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    run_id          TEXT REFERENCES run(id),
    created_at      TEXT NOT NULL,
    claimed_at      TEXT,
    finished_at     TEXT
);

-- coalescing: at most one *queued* wake per key — a flurry of identical triggers folds into one
CREATE UNIQUE INDEX wake_queued_key_uq ON wake(coalesce_key) WHERE status = 'queued';
CREATE INDEX wake_employee_status_idx ON wake(employee_id, status);
