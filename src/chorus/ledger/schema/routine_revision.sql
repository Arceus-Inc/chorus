-- routine_revision — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE routine_revision (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                        uuid PRIMARY KEY,
    routine_id                uuid NOT NULL REFERENCES routine(id),
    revision_no               integer NOT NULL,
    intent_template           text NOT NULL,
    target                    text NOT NULL,
    concurrency_policy        text NOT NULL,
    catch_up_policy           text NOT NULL,
    env                       jsonb,
    change_summary            text,
    restored_from_revision_id uuid REFERENCES routine_revision(id),
    created_at                timestamptz NOT NULL
);

ALTER TABLE routine_revision ENABLE ROW LEVEL SECURITY;

ALTER TABLE routine_revision FORCE ROW LEVEL SECURITY;

CREATE POLICY routine_revision_company_isolation ON routine_revision USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX routine_revision_no_uq ON routine_revision(routine_id, revision_no);
