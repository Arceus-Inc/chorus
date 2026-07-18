-- team — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE team (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                      uuid PRIMARY KEY,
    name                    text NOT NULL,
    lead_employee_id        text NOT NULL,
    goal_id                 uuid REFERENCES goal(id),
    parent_team_id          uuid REFERENCES team(id),
    status                  text NOT NULL DEFAULT 'forming',
    policy_version          integer NOT NULL DEFAULT 1,
    created_by              text NOT NULL,
    created_at              timestamptz NOT NULL,
    activated_at            timestamptz,
    archived_at             timestamptz,
    FOREIGN KEY (company_id, lead_employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE team ENABLE ROW LEVEL SECURITY;

ALTER TABLE team FORCE ROW LEVEL SECURITY;

CREATE POLICY team_company_isolation ON team USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX team_lead_status_idx ON team(lead_employee_id, status);

CREATE INDEX team_goal_idx ON team(goal_id);
