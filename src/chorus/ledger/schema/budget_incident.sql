-- budget_incident — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE budget_incident (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id              uuid PRIMARY KEY,
    policy_id       uuid NOT NULL REFERENCES budget_policy(id),
    threshold_type  text NOT NULL,
    amount_limit    bigint NOT NULL,
    amount_observed bigint NOT NULL,
    window_start    timestamptz NOT NULL,
    status          text NOT NULL DEFAULT 'open',
    approval_id     uuid REFERENCES approval(id),
    created_at      timestamptz NOT NULL
);

ALTER TABLE budget_incident ENABLE ROW LEVEL SECURITY;

ALTER TABLE budget_incident FORCE ROW LEVEL SECURITY;

CREATE POLICY budget_incident_company_isolation ON budget_incident USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX budget_incident_window_uq
    ON budget_incident(policy_id, window_start, threshold_type) WHERE status <> 'dismissed';
