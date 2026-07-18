-- cost_event — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE cost_event (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id            uuid PRIMARY KEY,
    employee_id   text NOT NULL,
    task_id       uuid REFERENCES task(id),
    run_id        uuid REFERENCES run(id),
    provider      text NOT NULL,
    model         text NOT NULL,
    input_tokens  bigint NOT NULL DEFAULT 0,
    output_tokens bigint NOT NULL DEFAULT 0,
    cost_cents    bigint NOT NULL,
    occurred_at   timestamptz NOT NULL,
    CONSTRAINT cost_event_nonneg CHECK (cost_cents >= 0 AND input_tokens >= 0 AND output_tokens >= 0),
    FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE cost_event ENABLE ROW LEVEL SECURITY;

ALTER TABLE cost_event FORCE ROW LEVEL SECURITY;

CREATE POLICY cost_event_company_isolation ON cost_event USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX cost_event_employee_idx ON cost_event(employee_id, occurred_at);
