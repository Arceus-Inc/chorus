-- goal — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE goal (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                uuid PRIMARY KEY,
    title             text NOT NULL,
    level             text NOT NULL DEFAULT 'company',
    status            text NOT NULL DEFAULT 'active',
    parent_id         uuid REFERENCES goal(id),
    owner_employee_id text,
    created_at        timestamptz NOT NULL,
    updated_at        timestamptz NOT NULL,
    FOREIGN KEY (company_id, owner_employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE goal ENABLE ROW LEVEL SECURITY;

ALTER TABLE goal FORCE ROW LEVEL SECURITY;

CREATE POLICY goal_company_isolation ON goal USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));
