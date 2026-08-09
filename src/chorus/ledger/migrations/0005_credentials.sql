-- 0005_credentials — org-owned credential brokerage state (registration, ask, grant,
-- opaque lease, usage). Plaintext secrets never live here — only policy + grant
-- metadata; materialization reads from an external SecretSource (env / AWS / layered).
-- Mirrors schema/credential_*.sql (house pattern: company_id + FORCE RLS, uuid ids).
-- Immutable once applied: author a new migration instead of editing this one.
--
-- Create order matches FK dependencies (registration → grant → ask → lease/use).

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
