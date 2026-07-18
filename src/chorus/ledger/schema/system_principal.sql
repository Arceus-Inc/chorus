-- system_principal — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE system_principal (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id           text,
    kind         text NOT NULL,
    display_name text NOT NULL,
    purpose      text NOT NULL,
    created_at   timestamptz NOT NULL,
    PRIMARY KEY (company_id, id)
);

ALTER TABLE system_principal ENABLE ROW LEVEL SECURITY;

ALTER TABLE system_principal FORCE ROW LEVEL SECURITY;

CREATE POLICY system_principal_company_isolation ON system_principal USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));
