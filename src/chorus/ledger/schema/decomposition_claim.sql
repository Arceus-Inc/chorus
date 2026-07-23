-- decomposition_claim — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE decomposition_claim (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                        uuid PRIMARY KEY,
    source_task_id            uuid NOT NULL REFERENCES task(id),
    accepted_plan_revision_id uuid NOT NULL REFERENCES artifact_revision(id),
    status                    text NOT NULL DEFAULT 'in_flight',
    request_fingerprint       text NOT NULL DEFAULT '',
    requested_children        jsonb NOT NULL DEFAULT '[]',
    child_task_ids            jsonb NOT NULL DEFAULT '[]',
    owner_run_id              uuid REFERENCES run(id),
    completed_at              timestamptz,
    created_at                timestamptz NOT NULL
);

ALTER TABLE decomposition_claim ENABLE ROW LEVEL SECURITY;

ALTER TABLE decomposition_claim FORCE ROW LEVEL SECURITY;

CREATE POLICY decomposition_claim_company_isolation ON decomposition_claim USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX decomp_source_revision_uq
    ON decomposition_claim(source_task_id, accepted_plan_revision_id);

CREATE INDEX decomp_active_owner_idx ON decomposition_claim(owner_run_id)
    WHERE status = 'in_flight';
