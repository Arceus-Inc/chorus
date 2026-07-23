-- wake — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE wake (
    id              uuid PRIMARY KEY,
    employee_id     text NOT NULL,
    reason          text NOT NULL,
    payload         jsonb NOT NULL DEFAULT '{}',
    status          text NOT NULL DEFAULT 'queued',
    coalesce_key    text NOT NULL,
    coalesced_count integer NOT NULL DEFAULT 0,
    idempotency_key text,
    run_id          uuid REFERENCES run(id),
    created_at      timestamptz NOT NULL,
    claimed_at      timestamptz,
    finished_at     timestamptz,
    task_id         uuid,
    company_id      uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE wake ENABLE ROW LEVEL SECURITY;

ALTER TABLE wake FORCE ROW LEVEL SECURITY;

CREATE POLICY wake_company_isolation ON wake USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX wake_queued_key_uq ON wake(company_id, coalesce_key) WHERE status = 'queued';

CREATE INDEX wake_employee_status_idx ON wake(employee_id, status);

CREATE INDEX wake_queue_idx ON wake(status, created_at, id);
