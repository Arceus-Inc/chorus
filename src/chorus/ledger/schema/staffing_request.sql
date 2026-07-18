-- staffing_request — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE staffing_request (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                          uuid PRIMARY KEY,
    task_id                     uuid NOT NULL REFERENCES task(id),
    goal_id                     text NOT NULL,
    team_id                     uuid NOT NULL REFERENCES team(id),
    requested_by_employee_id    text NOT NULL,
    rationale                   text NOT NULL,
    status                      text NOT NULL DEFAULT 'open',
    workforce_plan_id           uuid,
    created_at                  timestamptz NOT NULL,
    resolved_at                 timestamptz,
    FOREIGN KEY (company_id, requested_by_employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE staffing_request ENABLE ROW LEVEL SECURITY;

ALTER TABLE staffing_request FORCE ROW LEVEL SECURITY;

CREATE POLICY staffing_request_company_isolation ON staffing_request USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX staffing_request_status_idx ON staffing_request(status, created_at);
