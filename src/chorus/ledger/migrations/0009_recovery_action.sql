-- Migration 0009 — recovery_action (spec 01 Cluster B): liveness-as-visibility.
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Declarative copy lives in ../schema/recovery_action.sql; test_schema_parity asserts agreement.

CREATE TABLE recovery_action (
    id                         TEXT PRIMARY KEY,
    source_task_id             TEXT NOT NULL REFERENCES task(id),
    recovery_task_id           TEXT REFERENCES task(id),
    kind                       TEXT NOT NULL,
    status                     TEXT NOT NULL DEFAULT 'active',
    owner_employee_id          TEXT REFERENCES employee(id),
    owner_user_id              TEXT,
    previous_owner_employee_id TEXT REFERENCES employee(id),
    return_owner_employee_id   TEXT REFERENCES employee(id),
    cause                      TEXT NOT NULL DEFAULT '',
    fingerprint                TEXT NOT NULL DEFAULT '',
    evidence                   TEXT NOT NULL DEFAULT '{}',
    next_action                TEXT,
    wake_policy                TEXT NOT NULL DEFAULT '{}',
    monitor_policy             TEXT NOT NULL DEFAULT '{}',
    attempt_count              INTEGER NOT NULL DEFAULT 0,
    max_attempts               INTEGER NOT NULL DEFAULT 0,
    timeout_at                 TEXT,
    last_attempt_at            TEXT,
    resolved_at                TEXT,
    outcome                    TEXT,
    resolution_note            TEXT,
    created_at                 TEXT NOT NULL
);

-- at most one open recovery per source task
CREATE UNIQUE INDEX recovery_active_source_uq ON recovery_action(source_task_id)
    WHERE status IN ('active', 'escalated');

-- and at most one per (source, cause, fingerprint)
CREATE UNIQUE INDEX recovery_active_fingerprint_uq
    ON recovery_action(source_task_id, cause, fingerprint)
    WHERE status IN ('active', 'escalated');
