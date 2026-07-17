-- employee — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE employee (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                   text,
    name                 text NOT NULL,
    role                 text NOT NULL,
    reports_to           text,
    memory_scope         text NOT NULL DEFAULT 'project',
    status               text NOT NULL DEFAULT 'idle',
    budget_monthly_cents bigint NOT NULL DEFAULT 0,
    spent_monthly_cents  bigint NOT NULL DEFAULT 0,
    pause_reason         text,
    paused_at            timestamptz,
    last_beat_at         timestamptz,
    created_at           timestamptz NOT NULL,
    updated_at           timestamptz NOT NULL,
    PRIMARY KEY (company_id, id),
    FOREIGN KEY (company_id, reports_to) REFERENCES employee (company_id, id)
);

ALTER TABLE employee ENABLE ROW LEVEL SECURITY;

ALTER TABLE employee FORCE ROW LEVEL SECURITY;

CREATE POLICY employee_company_isolation ON employee USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX employee_reports_to_idx ON employee(reports_to);
