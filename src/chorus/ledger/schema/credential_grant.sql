-- credential_grant — approved once/standing grant (opaque; no secret material).
-- Postgres-native (uuid/timestamptz/jsonb; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE credential_grant (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id             uuid PRIMARY KEY,
    credential     text NOT NULL,
    audience       text NOT NULL,
    status         text NOT NULL DEFAULT 'active',
    mode           text NOT NULL,
    purpose        text NOT NULL,
    granted_at     timestamptz NOT NULL,
    expires_at     timestamptz,
    FOREIGN KEY (company_id, credential)
        REFERENCES credential_registration(company_id, credential)
);

ALTER TABLE credential_grant ENABLE ROW LEVEL SECURITY;

ALTER TABLE credential_grant FORCE ROW LEVEL SECURITY;

CREATE POLICY credential_grant_company_isolation ON credential_grant
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX credential_grant_standing_idx
    ON credential_grant(company_id, credential, audience, mode, status);
