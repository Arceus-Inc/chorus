-- delegation_contract — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE delegation_contract (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    task_id                    uuid PRIMARY KEY REFERENCES task(id),
    team_id                    uuid NOT NULL REFERENCES team(id),
    lead_employee_id           text NOT NULL,
    management_profile_version integer NOT NULL,
    parent_contract_task_id    uuid REFERENCES delegation_contract(task_id),
    can_subdelegate            boolean NOT NULL DEFAULT false,
    max_depth                  integer NOT NULL DEFAULT 0,
    max_team_size              integer NOT NULL DEFAULT 1,
    spend_limit_cents          bigint,
    objective_rubric           text NOT NULL,
    status                     text NOT NULL DEFAULT 'forming',
    accepted_run_id            text,
    accepted_at                timestamptz,
    created_at                 timestamptz NOT NULL,
    updated_at                 timestamptz NOT NULL,
    FOREIGN KEY (company_id, lead_employee_id) REFERENCES employee (company_id, id)
    , max_direct_children      INTEGER);

ALTER TABLE delegation_contract ENABLE ROW LEVEL SECURITY;

ALTER TABLE delegation_contract FORCE ROW LEVEL SECURITY;

CREATE POLICY delegation_contract_company_isolation ON delegation_contract USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX delegation_contract_team_status_idx ON delegation_contract(team_id, status);

CREATE INDEX delegation_contract_lead_status_idx ON delegation_contract(lead_employee_id, status);
