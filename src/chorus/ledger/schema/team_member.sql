-- team_member — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE team_member (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    team_id                 uuid NOT NULL REFERENCES team(id),
    employee_id             text NOT NULL,
    membership_role         text NOT NULL DEFAULT 'member',
    can_subdelegate         boolean NOT NULL DEFAULT false,
    source_manager_id       text NOT NULL,
    joined_at               timestamptz NOT NULL,
    left_at                 timestamptz,
    PRIMARY KEY (team_id, employee_id),
    FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id),
    FOREIGN KEY (company_id, source_manager_id) REFERENCES employee (company_id, id)
);

ALTER TABLE team_member ENABLE ROW LEVEL SECURITY;

ALTER TABLE team_member FORCE ROW LEVEL SECURITY;

CREATE POLICY team_member_company_isolation ON team_member USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX team_member_employee_idx ON team_member(employee_id, left_at);
