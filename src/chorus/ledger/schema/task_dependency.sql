-- task_dependency — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE task_dependency (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id            uuid PRIMARY KEY,
    task_id       uuid NOT NULL REFERENCES task(id),
    depends_on_id uuid NOT NULL REFERENCES task(id),
    created_at    timestamptz NOT NULL,
    CONSTRAINT task_dependency_no_self CHECK (task_id <> depends_on_id)
);

ALTER TABLE task_dependency ENABLE ROW LEVEL SECURITY;

ALTER TABLE task_dependency FORCE ROW LEVEL SECURITY;

CREATE POLICY task_dependency_company_isolation ON task_dependency USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX task_dependency_uq ON task_dependency(task_id, depends_on_id);

CREATE INDEX task_dependency_depends_on_idx ON task_dependency(depends_on_id);
