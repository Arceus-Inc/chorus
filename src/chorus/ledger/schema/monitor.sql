-- Cluster B: monitor (deferred one-shot self-wake). Declarative; applied via migrations/.
CREATE TABLE monitor (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES task(id),
    employee_id     TEXT NOT NULL REFERENCES employee(id),
    next_check_at   TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    notes           TEXT,
    external_ref    TEXT,
    timeout_at      TEXT,
    max_attempts    INTEGER NOT NULL DEFAULT 1,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    recovery_policy TEXT NOT NULL DEFAULT 'wake_owner',
    created_at      TEXT NOT NULL,
    fired_at        TEXT,
    CONSTRAINT monitor_armed_has_schedule CHECK (status <> 'pending' OR next_check_at IS NOT NULL),
    CONSTRAINT monitor_attempts CHECK (
        attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts)
);

CREATE UNIQUE INDEX monitor_armed_task_uq ON monitor(task_id) WHERE status = 'pending';

CREATE INDEX monitor_due_idx ON monitor(next_check_at) WHERE status = 'pending';
