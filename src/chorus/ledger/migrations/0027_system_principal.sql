-- Migration 0027 — durable non-workforce attribution for system verification runs.

CREATE TABLE system_principal (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    display_name TEXT NOT NULL,
    purpose      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

INSERT INTO system_principal (id, kind, display_name, purpose, created_at)
VALUES (
    'system-verifier',
    'verification',
    'System Verifier',
    'Independent read-only verification of employee-authored work',
    '1970-01-01T00:00:00+00:00'
);

PRAGMA legacy_alter_table=ON;

ALTER TABLE run RENAME TO run__old;

CREATE TABLE run (
    id                   TEXT PRIMARY KEY,
    employee_id          TEXT NOT NULL REFERENCES employee(id),
    task_id              TEXT NOT NULL REFERENCES task(id),
    wake_id              TEXT,
    status               TEXT NOT NULL DEFAULT 'queued',
    lease_expires_at     TEXT,
    liveness_state       TEXT,
    continuation_attempt INTEGER NOT NULL DEFAULT 0,
    outcome              TEXT NOT NULL DEFAULT '{}',
    usage                TEXT NOT NULL DEFAULT '{}',
    started_at           TEXT,
    finished_at          TEXT,
    created_at           TEXT NOT NULL,
    principal_kind       TEXT NOT NULL DEFAULT 'employee'
                         CHECK (principal_kind IN ('employee', 'system')),
    system_principal_id  TEXT REFERENCES system_principal(id)
                         CHECK (
                             (principal_kind = 'employee' AND system_principal_id IS NULL)
                             OR (principal_kind = 'system' AND system_principal_id IS NOT NULL)
                         )
);

INSERT INTO run (
    id, employee_id, task_id, wake_id, status, lease_expires_at, liveness_state,
    continuation_attempt, outcome, usage, started_at, finished_at, created_at
)
SELECT
    id, employee_id, task_id, wake_id, status, lease_expires_at, liveness_state,
    continuation_attempt, outcome, usage, started_at, finished_at, created_at
FROM run__old;

DROP TABLE run__old;

CREATE INDEX run_employee_started_idx ON run(employee_id, started_at);
CREATE INDEX run_status_lease_idx ON run(status, lease_expires_at);
CREATE INDEX run_system_principal_idx ON run(system_principal_id, started_at);

ALTER TABLE activity RENAME TO activity__old;

CREATE TABLE activity (
    id                 TEXT PRIMARY KEY,
    actor_employee_id  TEXT,
    actor_user_id      TEXT,
    actor_system_principal_id TEXT REFERENCES system_principal(id),
    verb               TEXT NOT NULL,
    subject_kind       TEXT NOT NULL,
    subject_id         TEXT NOT NULL,
    trace_id           TEXT,
    payload            TEXT NOT NULL DEFAULT '{}',
    occurred_at        TEXT NOT NULL,
    CONSTRAINT activity_single_actor CHECK (
        (actor_employee_id IS NULL OR actor_user_id IS NULL)
        AND (actor_employee_id IS NULL OR actor_system_principal_id IS NULL)
        AND (actor_user_id IS NULL OR actor_system_principal_id IS NULL)
    )
);

INSERT INTO activity (
    id, actor_employee_id, actor_user_id, verb, subject_kind, subject_id, trace_id, payload, occurred_at
)
SELECT
    id, actor_employee_id, actor_user_id, verb, subject_kind, subject_id, trace_id, payload, occurred_at
FROM activity__old;

DROP TABLE activity__old;

CREATE INDEX activity_subject_idx
    ON activity(subject_kind, subject_id, occurred_at, id);
CREATE INDEX activity_occurred_idx ON activity(occurred_at);

PRAGMA legacy_alter_table=OFF;