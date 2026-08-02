-- credential_lease — opaque materialization handle for a grant+session.
-- Postgres-native (uuid/timestamptz/jsonb; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE credential_lease (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    handle         text NOT NULL,
    grant_id       uuid NOT NULL REFERENCES credential_grant(id) ON DELETE CASCADE,
    session        text NOT NULL,
    issued_at      timestamptz NOT NULL,
    PRIMARY KEY (company_id, handle)
);

ALTER TABLE credential_lease ENABLE ROW LEVEL SECURITY;

ALTER TABLE credential_lease FORCE ROW LEVEL SECURITY;

CREATE POLICY credential_lease_company_isolation ON credential_lease
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX credential_lease_grant_idx
    ON credential_lease(company_id, grant_id);
