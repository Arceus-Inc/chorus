-- workforce_plan_management_grant — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE workforce_plan_management_grant (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    plan_id                     uuid NOT NULL,
    plan_revision               integer NOT NULL,
    employee_ref                text NOT NULL,
    can_lead                    boolean NOT NULL DEFAULT false,
    can_subdelegate             boolean NOT NULL DEFAULT false,
    max_delegation_depth        integer NOT NULL DEFAULT 0,
    max_team_size               integer NOT NULL DEFAULT 1,
    allowed_professions         jsonb NOT NULL DEFAULT '[]',
    spend_limit_cents           bigint,
    position                    integer NOT NULL DEFAULT 0,
    PRIMARY KEY (plan_id, plan_revision, employee_ref),
    FOREIGN KEY (plan_id, plan_revision) REFERENCES workforce_plan(id, revision)
);

ALTER TABLE workforce_plan_management_grant ENABLE ROW LEVEL SECURITY;

ALTER TABLE workforce_plan_management_grant FORCE ROW LEVEL SECURITY;

CREATE POLICY workforce_plan_management_grant_company_isolation ON workforce_plan_management_grant USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));
