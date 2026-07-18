-- run — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE run (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                   uuid PRIMARY KEY,
    employee_id          text NOT NULL,
    task_id              uuid NOT NULL REFERENCES task(id),
    wake_id              uuid,
    status               text NOT NULL DEFAULT 'queued',
    lease_expires_at     timestamptz,
    liveness_state       text,
    continuation_attempt integer NOT NULL DEFAULT 0,
    outcome              jsonb NOT NULL DEFAULT '{}',
    usage                jsonb NOT NULL DEFAULT '{}',
    started_at           timestamptz,
    finished_at          timestamptz,
    created_at           timestamptz NOT NULL,
    principal_kind       text NOT NULL DEFAULT 'employee'
                         CHECK (principal_kind IN ('employee', 'system')),
    system_principal_id  text
                         CHECK (
                             (principal_kind = 'employee' AND system_principal_id IS NULL)
                             OR (principal_kind = 'system' AND system_principal_id IS NOT NULL)
                         ),
    FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id),
    FOREIGN KEY (company_id, system_principal_id) REFERENCES system_principal (company_id, id)
);

ALTER TABLE run ENABLE ROW LEVEL SECURITY;

ALTER TABLE run FORCE ROW LEVEL SECURITY;

CREATE POLICY run_company_isolation ON run USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX run_employee_started_idx ON run(employee_id, started_at);

CREATE INDEX run_status_lease_idx ON run(status, lease_expires_at);

CREATE INDEX run_system_principal_idx ON run(system_principal_id, started_at);
