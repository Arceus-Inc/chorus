-- routine — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE routine (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                 uuid PRIMARY KEY,
    employee_id        text NOT NULL,
    goal_id            uuid REFERENCES goal(id),
    parent_task_id     uuid REFERENCES task(id),
    intent_template    text NOT NULL,
    target             text NOT NULL DEFAULT 'spawn_task',
    concurrency_policy text NOT NULL DEFAULT 'coalesce',
    catch_up_policy    text NOT NULL DEFAULT 'skip_missed',
    status             text NOT NULL DEFAULT 'active',
    env                jsonb,
    routine_key        text,
    latest_revision_id uuid,
    latest_revision_no integer NOT NULL DEFAULT 1,
    created_at         timestamptz NOT NULL,
    updated_at         timestamptz NOT NULL,
    FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE routine ADD FOREIGN KEY (latest_revision_id) REFERENCES routine_revision(id);

ALTER TABLE routine ENABLE ROW LEVEL SECURITY;

ALTER TABLE routine FORCE ROW LEVEL SECURITY;

CREATE POLICY routine_company_isolation ON routine USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX routine_employee_key_uq ON routine (company_id, employee_id, routine_key)
    WHERE routine_key IS NOT NULL;
