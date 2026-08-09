-- 0006_run_carryover — typed, reassignment-safe landed beat context.

CREATE TABLE run_carryover (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    run_id uuid PRIMARY KEY REFERENCES run(id),
    phase text NOT NULL,
    recovery_hint text NOT NULL,
    evaluator_notes text[] NOT NULL DEFAULT '{}',
    files_touched text[] NOT NULL DEFAULT '{}',
    todo_digest text NOT NULL DEFAULT '',
    summary text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL
);

ALTER TABLE run_carryover ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_carryover FORCE ROW LEVEL SECURITY;
CREATE POLICY run_carryover_company_isolation ON run_carryover
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));
CREATE INDEX run_task_created_idx ON run (task_id, created_at);
