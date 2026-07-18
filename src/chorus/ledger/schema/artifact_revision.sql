-- artifact_revision — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE artifact_revision (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                uuid PRIMARY KEY,
    artifact_id       uuid NOT NULL REFERENCES artifact(id),
    revision          integer NOT NULL,
    resource_ref      jsonb,
    summary           text,
    created_by_run_id uuid REFERENCES run(id),
    created_at        timestamptz NOT NULL
);

ALTER TABLE artifact_revision ENABLE ROW LEVEL SECURITY;

ALTER TABLE artifact_revision FORCE ROW LEVEL SECURITY;

CREATE POLICY artifact_revision_company_isolation ON artifact_revision USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX artifact_revision_seq_uq ON artifact_revision(artifact_id, revision);
