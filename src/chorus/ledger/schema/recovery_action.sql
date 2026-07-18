-- recovery_action — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE recovery_action (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                         uuid PRIMARY KEY,
    source_task_id             uuid NOT NULL REFERENCES task(id),
    recovery_task_id           uuid REFERENCES task(id),
    kind                       text NOT NULL,
    status                     text NOT NULL DEFAULT 'active',
    owner_employee_id          text,
    owner_user_id              text,
    previous_owner_employee_id text,
    return_owner_employee_id   text,
    cause                      text NOT NULL DEFAULT '',
    fingerprint                text NOT NULL DEFAULT '',
    evidence                   jsonb NOT NULL DEFAULT '{}',
    next_action                text,
    wake_policy                jsonb NOT NULL DEFAULT '{}',
    monitor_policy             jsonb NOT NULL DEFAULT '{}',
    attempt_count              integer NOT NULL DEFAULT 0,
    max_attempts               integer NOT NULL DEFAULT 0,
    timeout_at                 timestamptz,
    last_attempt_at            timestamptz,
    resolved_at                timestamptz,
    outcome                    text,
    resolution_note            text,
    created_at                 timestamptz NOT NULL,
    CONSTRAINT recovery_attempts CHECK (
        attempt_count >= 0 AND max_attempts >= 0 AND attempt_count <= max_attempts),
    FOREIGN KEY (company_id, owner_employee_id) REFERENCES employee (company_id, id),
    FOREIGN KEY (company_id, previous_owner_employee_id) REFERENCES employee (company_id, id),
    FOREIGN KEY (company_id, return_owner_employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE recovery_action ENABLE ROW LEVEL SECURITY;

ALTER TABLE recovery_action FORCE ROW LEVEL SECURITY;

CREATE POLICY recovery_action_company_isolation ON recovery_action USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX recovery_active_source_uq ON recovery_action(source_task_id)
    WHERE status IN ('active', 'escalated');

CREATE UNIQUE INDEX recovery_active_fingerprint_uq
    ON recovery_action(source_task_id, cause, fingerprint)
    WHERE status IN ('active', 'escalated');
