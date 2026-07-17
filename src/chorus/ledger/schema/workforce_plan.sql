-- workforce_plan — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE workforce_plan (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                          uuid NOT NULL,
    revision                    integer NOT NULL,
    status                      text NOT NULL,
    proposed_by_employee_id     text NOT NULL,
    rationale                   text NOT NULL,
    confidence                  double precision NOT NULL,
    source_goal_ids             jsonb NOT NULL DEFAULT '[]',
    revised_by_user_id          text,
    decided_by_user_id          text,
    created_at                  timestamptz NOT NULL,
    decided_at                  timestamptz,
    staffing_request_id         uuid REFERENCES staffing_request(id),
    PRIMARY KEY (id, revision),
    FOREIGN KEY (company_id, proposed_by_employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE workforce_plan ENABLE ROW LEVEL SECURITY;

ALTER TABLE workforce_plan FORCE ROW LEVEL SECURITY;

CREATE POLICY workforce_plan_company_isolation ON workforce_plan USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX workforce_plan_status_idx ON workforce_plan(status, created_at);
