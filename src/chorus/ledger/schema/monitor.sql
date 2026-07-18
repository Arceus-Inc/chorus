-- monitor — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE monitor (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id              uuid PRIMARY KEY,
    task_id         uuid NOT NULL REFERENCES task(id),
    employee_id     text NOT NULL,
    next_check_at   timestamptz,
    status          text NOT NULL DEFAULT 'pending',
    notes           text,
    external_ref    text,
    timeout_at      timestamptz,
    max_attempts    integer NOT NULL DEFAULT 1,
    attempt_count   integer NOT NULL DEFAULT 0,
    recovery_policy text NOT NULL DEFAULT 'wake_owner',
    created_at      timestamptz NOT NULL,
    fired_at        timestamptz,
    CONSTRAINT monitor_armed_has_schedule CHECK (status <> 'pending' OR next_check_at IS NOT NULL),
    CONSTRAINT monitor_attempts CHECK (
        attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts),
    FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE monitor ENABLE ROW LEVEL SECURITY;

ALTER TABLE monitor FORCE ROW LEVEL SECURITY;

CREATE POLICY monitor_company_isolation ON monitor USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX monitor_armed_task_uq ON monitor(task_id) WHERE status = 'pending';

CREATE INDEX monitor_due_idx ON monitor(next_check_at) WHERE status = 'pending';
