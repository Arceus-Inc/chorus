-- decision_record — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE decision_record (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                    uuid PRIMARY KEY,
    task_id               uuid NOT NULL,
    option                text NOT NULL,
    rationale             text NOT NULL,
    confidence            double precision NOT NULL,
    outcome_metric        text NOT NULL,
    revisit_trigger       text NOT NULL,
    rejected_alternatives jsonb NOT NULL DEFAULT '[]',
    superseded_by         uuid,
    created_at            timestamptz NOT NULL
);

ALTER TABLE decision_record ENABLE ROW LEVEL SECURITY;

ALTER TABLE decision_record FORCE ROW LEVEL SECURITY;

CREATE POLICY decision_record_company_isolation ON decision_record USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX decision_record_task ON decision_record(task_id);
