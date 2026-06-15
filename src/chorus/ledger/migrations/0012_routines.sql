-- Migration 0012 — routines (spec 01 Cluster C): cron (routine + trigger + run).
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Declarative copies live in ../schema/{routine,routine_trigger,routine_run}.sql.

CREATE TABLE routine (
    id                 TEXT PRIMARY KEY,
    employee_id        TEXT NOT NULL REFERENCES employee(id),
    goal_id            TEXT REFERENCES goal(id),
    parent_task_id     TEXT REFERENCES task(id),
    intent_template    TEXT NOT NULL,
    target             TEXT NOT NULL DEFAULT 'spawn_task',
    concurrency_policy TEXT NOT NULL DEFAULT 'skip_if_active',
    catch_up_policy    TEXT NOT NULL DEFAULT 'skip_missed',
    status             TEXT NOT NULL DEFAULT 'active',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE routine_trigger (
    id              TEXT PRIMARY KEY,
    routine_id      TEXT NOT NULL REFERENCES routine(id),
    kind            TEXT NOT NULL DEFAULT 'cron',
    cron_expression TEXT,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    next_run_at     TEXT,
    last_fired_at   TEXT,
    created_at      TEXT NOT NULL
);

-- the scheduler's due-scan target (also the double-fire-guard column)
CREATE INDEX routine_trigger_next_run_idx ON routine_trigger(next_run_at);

CREATE TABLE routine_run (
    id                    TEXT PRIMARY KEY,
    routine_id            TEXT NOT NULL REFERENCES routine(id),
    trigger_id            TEXT NOT NULL REFERENCES routine_trigger(id),
    status                TEXT NOT NULL DEFAULT 'received',
    dispatch_fingerprint  TEXT NOT NULL DEFAULT '',
    idempotency_key       TEXT,
    linked_task_id        TEXT REFERENCES task(id),
    coalesced_into_run_id TEXT,
    created_at            TEXT NOT NULL
);

-- exact-once dispatch per idempotency key
CREATE UNIQUE INDEX routine_run_idempotency_uq ON routine_run(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
