-- Migration 0017 — task.trust_preset + task.trust_boundary (spec 04 §4 trust presets).
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- The task's trust posture: trust_preset ('standard' | 'low_trust_review' | NULL → policy derives) and
-- trust_boundary (JSON {secret_ref_allowlist:[…]} | NULL — the concrete scope a low-trust beat needs).
-- Done by the rename-old rebuild (CREATE the final table directly, not ALTER ADD COLUMN) so the stored
-- DDL matches the declarative schema/task.sql (parity test, cf. migrations 0014/0015/0016). task is
-- referenced by many tables (parent_id self-ref, dod/run/wake/dependency/…); legacy_alter_table keeps
-- those FKs pointing at the rebuilt table across the rename.

PRAGMA legacy_alter_table=ON;

ALTER TABLE task RENAME TO task__old;

CREATE TABLE task (
    id                     TEXT PRIMARY KEY,
    parent_id              TEXT REFERENCES task(id),
    goal_id                TEXT REFERENCES goal(id),
    intent                 TEXT NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'backlog',
    priority               TEXT NOT NULL DEFAULT 'medium',
    assignee_employee_id   TEXT REFERENCES employee(id),
    assignee_user_id       TEXT,
    checkout_run_id        TEXT,
    execution_run_id       TEXT,
    depth                  INTEGER NOT NULL DEFAULT 0,
    request_depth          INTEGER NOT NULL DEFAULT 0,
    origin_kind            TEXT NOT NULL DEFAULT 'manual',
    origin_id              TEXT,
    origin_fingerprint     TEXT NOT NULL DEFAULT 'default',
    created_by_employee_id TEXT,
    created_by_user_id     TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    started_at             TEXT,
    completed_at           TEXT,
    cancelled_at           TEXT,
    trust_preset           TEXT,
    trust_boundary         TEXT,
    CONSTRAINT task_single_assignee
        CHECK (assignee_employee_id IS NULL OR assignee_user_id IS NULL)
);

INSERT INTO task (id, parent_id, goal_id, intent, status, priority, assignee_employee_id,
                  assignee_user_id, checkout_run_id, execution_run_id, depth, request_depth,
                  origin_kind, origin_id, origin_fingerprint, created_by_employee_id,
                  created_by_user_id, created_at, updated_at, started_at, completed_at, cancelled_at,
                  trust_preset, trust_boundary)
    SELECT id, parent_id, goal_id, intent, status, priority, assignee_employee_id,
           assignee_user_id, checkout_run_id, execution_run_id, depth, request_depth,
           origin_kind, origin_id, origin_fingerprint, created_by_employee_id,
           created_by_user_id, created_at, updated_at, started_at, completed_at, cancelled_at,
           NULL, NULL
    FROM task__old;

DROP TABLE task__old;

CREATE INDEX task_assignee_status_idx ON task(assignee_employee_id, status);
CREATE INDEX task_parent_idx ON task(parent_id);
CREATE INDEX task_goal_idx ON task(goal_id);
CREATE INDEX task_status_idx ON task(status);
CREATE INDEX task_origin_idx ON task(origin_kind, origin_id);

CREATE UNIQUE INDEX task_open_routine_uq
    ON task(origin_kind, origin_id, origin_fingerprint)
    WHERE origin_kind = 'routine_execution' AND origin_id IS NOT NULL
          AND execution_run_id IS NOT NULL
          AND status IN ('backlog','todo','in_progress','in_review','blocked');

CREATE UNIQUE INDEX task_active_stranded_recovery_uq
    ON task(origin_kind, origin_id)
    WHERE origin_kind = 'stranded_recovery' AND origin_id IS NOT NULL
          AND status NOT IN ('done','cancelled');

CREATE UNIQUE INDEX task_active_stale_run_eval_uq
    ON task(origin_kind, origin_id)
    WHERE origin_kind = 'stale_run_eval' AND origin_id IS NOT NULL
          AND status NOT IN ('done','cancelled');

CREATE UNIQUE INDEX task_active_productivity_review_uq
    ON task(origin_kind, origin_id)
    WHERE origin_kind = 'productivity_review' AND origin_id IS NOT NULL
          AND status NOT IN ('done','cancelled');

PRAGMA legacy_alter_table=OFF;
