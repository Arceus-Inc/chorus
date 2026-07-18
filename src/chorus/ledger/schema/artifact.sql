-- artifact — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE artifact (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id            uuid PRIMARY KEY,
    task_id       uuid NOT NULL REFERENCES task(id),
    type          text NOT NULL,
    provider      text,
    external_id   text,
    url           text,
    review_state  text,
    health_status text,
    is_primary    boolean NOT NULL DEFAULT false,
    resource_ref  jsonb,
    created_at    timestamptz NOT NULL,
    updated_at    timestamptz NOT NULL
);

ALTER TABLE artifact ENABLE ROW LEVEL SECURITY;

ALTER TABLE artifact FORCE ROW LEVEL SECURITY;

CREATE POLICY artifact_company_isolation ON artifact USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX artifact_task_idx ON artifact(task_id);
