-- dod — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE dod (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                 uuid PRIMARY KEY,
    task_id            uuid NOT NULL REFERENCES task(id),
    kind               text NOT NULL,
    spec               jsonb NOT NULL DEFAULT '{}',
    artifact_class     text,
    revision           integer NOT NULL DEFAULT 1,
    status             text NOT NULL DEFAULT 'pending',
    verdict            jsonb,
    verified_by_run_id uuid REFERENCES run(id),
    created_at         timestamptz NOT NULL,
    updated_at         timestamptz NOT NULL,
    proposed_revision  jsonb
);

ALTER TABLE dod ENABLE ROW LEVEL SECURITY;

ALTER TABLE dod FORCE ROW LEVEL SECURITY;

CREATE POLICY dod_company_isolation ON dod USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX dod_task_uq ON dod(task_id);

CREATE INDEX dod_kind_idx ON dod(kind);

CREATE INDEX dod_status_idx ON dod(status);
