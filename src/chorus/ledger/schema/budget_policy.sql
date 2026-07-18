-- budget_policy — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE budget_policy (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                uuid PRIMARY KEY,
    scope_type        text NOT NULL,
    scope_id          text NOT NULL,
    amount            bigint NOT NULL,
    metric            text NOT NULL DEFAULT 'cost_cents',
    warn_percent      integer NOT NULL DEFAULT 80,
    hard_stop_enabled boolean NOT NULL DEFAULT true,
    window_kind       text NOT NULL DEFAULT 'monthly',
    created_at        timestamptz NOT NULL,
    updated_at        timestamptz NOT NULL
);

ALTER TABLE budget_policy ENABLE ROW LEVEL SECURITY;

ALTER TABLE budget_policy FORCE ROW LEVEL SECURITY;

CREATE POLICY budget_policy_company_isolation ON budget_policy USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX budget_policy_scope_uq
    ON budget_policy (company_id, scope_type, scope_id, metric, window_kind);
