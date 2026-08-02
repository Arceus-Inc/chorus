-- credential_ask — pending owner-approval request for a registered credential.
-- Postgres-native (uuid/timestamptz/jsonb; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE credential_ask (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id             uuid PRIMARY KEY,
    credential     text NOT NULL,
    audience       text NOT NULL,
    purpose        text NOT NULL,
    requested_at   timestamptz NOT NULL,
    expires_at     timestamptz NOT NULL,
    status         text NOT NULL DEFAULT 'pending',
    grant_id       uuid REFERENCES credential_grant(id),
    FOREIGN KEY (company_id, credential)
        REFERENCES credential_registration(company_id, credential)
);

ALTER TABLE credential_ask ENABLE ROW LEVEL SECURITY;

ALTER TABLE credential_ask FORCE ROW LEVEL SECURITY;

CREATE POLICY credential_ask_company_isolation ON credential_ask
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX credential_ask_credential_status_idx
    ON credential_ask(company_id, credential, status);

CREATE INDEX credential_ask_expires_idx
    ON credential_ask(company_id, expires_at)
    WHERE status = 'pending';
