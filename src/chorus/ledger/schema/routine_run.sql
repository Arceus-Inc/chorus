-- routine_run — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE routine_run (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                    uuid PRIMARY KEY,
    routine_id            uuid NOT NULL REFERENCES routine(id),
    trigger_id            uuid NOT NULL REFERENCES routine_trigger(id),
    status                text NOT NULL DEFAULT 'received',
    dispatch_fingerprint  text NOT NULL DEFAULT '',
    idempotency_key       text,
    linked_task_id        uuid REFERENCES task(id),
    coalesced_into_run_id uuid,
    routine_revision_id   uuid REFERENCES routine_revision(id),
    created_at            timestamptz NOT NULL
);

ALTER TABLE routine_run ENABLE ROW LEVEL SECURITY;

ALTER TABLE routine_run FORCE ROW LEVEL SECURITY;

CREATE POLICY routine_run_company_isolation ON routine_run USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX routine_run_idempotency_uq ON routine_run (company_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
