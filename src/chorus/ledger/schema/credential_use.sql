-- credential_use — audit of sessions that materialized a grant.
-- Postgres-native (uuid/timestamptz/jsonb; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE credential_use (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    grant_id       uuid NOT NULL REFERENCES credential_grant(id) ON DELETE CASCADE,
    session        text NOT NULL,
    used_at        timestamptz NOT NULL,
    PRIMARY KEY (company_id, grant_id, session)
);

ALTER TABLE credential_use ENABLE ROW LEVEL SECURITY;

ALTER TABLE credential_use FORCE ROW LEVEL SECURITY;

CREATE POLICY credential_use_company_isolation ON credential_use
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX credential_use_grant_used_idx
    ON credential_use(grant_id, used_at);
