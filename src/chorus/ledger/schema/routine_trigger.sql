-- routine_trigger — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE routine_trigger (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id              uuid PRIMARY KEY,
    routine_id      uuid NOT NULL REFERENCES routine(id),
    kind            text NOT NULL DEFAULT 'cron',
    cron_expression text,
    timezone        text NOT NULL DEFAULT 'UTC',
    next_run_at     timestamptz,
    last_fired_at   timestamptz,
    created_at      timestamptz NOT NULL
);

ALTER TABLE routine_trigger ENABLE ROW LEVEL SECURITY;

ALTER TABLE routine_trigger FORCE ROW LEVEL SECURITY;

CREATE POLICY routine_trigger_company_isolation ON routine_trigger USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX routine_trigger_next_run_idx ON routine_trigger(next_run_at);
