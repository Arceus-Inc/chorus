-- activity — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE activity (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                 uuid PRIMARY KEY,
    actor_employee_id  text,
    actor_user_id      text,
    actor_system_principal_id text,
    verb               text NOT NULL,
    subject_kind       text NOT NULL,
    subject_id         text NOT NULL,
    trace_id           text,
    payload            jsonb NOT NULL DEFAULT '{}',
    occurred_at        timestamptz NOT NULL,
    CONSTRAINT activity_single_actor CHECK (
        (actor_employee_id IS NULL OR actor_user_id IS NULL)
        AND (actor_employee_id IS NULL OR actor_system_principal_id IS NULL)
        AND (actor_user_id IS NULL OR actor_system_principal_id IS NULL)
    ),
    FOREIGN KEY (company_id, actor_system_principal_id) REFERENCES system_principal (company_id, id)
);

ALTER TABLE activity ENABLE ROW LEVEL SECURITY;

ALTER TABLE activity FORCE ROW LEVEL SECURITY;

CREATE POLICY activity_company_isolation ON activity USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX activity_subject_idx ON activity(subject_kind, subject_id, occurred_at, id);

CREATE INDEX activity_occurred_idx ON activity(occurred_at);
