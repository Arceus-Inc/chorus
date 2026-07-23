-- workforce_plan_employee — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE workforce_plan_employee (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    plan_id                     uuid NOT NULL,
    plan_revision               integer NOT NULL,
    employee_ref                text NOT NULL,
    name                        text NOT NULL,
    profession                  text NOT NULL,
    reports_to_ref              text NOT NULL,
    responsibilities            jsonb NOT NULL DEFAULT '[]',
    budget_cents                bigint,
    position                    integer NOT NULL DEFAULT 0,
    PRIMARY KEY (plan_id, plan_revision, employee_ref),
    FOREIGN KEY (plan_id, plan_revision) REFERENCES workforce_plan(id, revision)
);

ALTER TABLE workforce_plan_employee ENABLE ROW LEVEL SECURITY;

ALTER TABLE workforce_plan_employee FORCE ROW LEVEL SECURITY;

CREATE POLICY workforce_plan_employee_company_isolation ON workforce_plan_employee USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));
