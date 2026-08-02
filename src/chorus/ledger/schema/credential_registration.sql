-- credential_registration — org credential policy (no plaintext secrets).
-- Postgres-native (uuid/timestamptz/jsonb; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE credential_registration (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    credential         text NOT NULL,
    source_name        text NOT NULL,
    owner              text NOT NULL,
    audience           text NOT NULL,
    purpose            text NOT NULL,
    mode               text NOT NULL,
    delivery           text NOT NULL,
    environment_key    text,
    allowed_host       text,
    injection_header   text NOT NULL,
    injection_scheme   text NOT NULL,
    allowed_methods    jsonb NOT NULL DEFAULT '[]'::jsonb,
    allowed_paths      jsonb NOT NULL DEFAULT '[]'::jsonb,
    requested_at       timestamptz NOT NULL,
    PRIMARY KEY (company_id, credential)
);

ALTER TABLE credential_registration ENABLE ROW LEVEL SECURITY;

ALTER TABLE credential_registration FORCE ROW LEVEL SECURITY;

CREATE POLICY credential_registration_company_isolation ON credential_registration
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX credential_registration_owner_idx
    ON credential_registration(company_id, owner);
