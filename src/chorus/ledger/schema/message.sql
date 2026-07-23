-- message — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE message (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id               uuid PRIMARY KEY,
    from_employee_id text,
    from_user_id     text,
    to_employee_id   text NOT NULL,
    task_id          uuid REFERENCES task(id),
    body             text NOT NULL,
    kind             text NOT NULL DEFAULT 'instruction',
    read_at          timestamptz,
    created_at       timestamptz NOT NULL,
    CONSTRAINT message_single_sender CHECK ((from_employee_id IS NULL) <> (from_user_id IS NULL)),
    FOREIGN KEY (company_id, from_employee_id) REFERENCES employee (company_id, id),
    FOREIGN KEY (company_id, to_employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE message ENABLE ROW LEVEL SECURITY;

ALTER TABLE message FORCE ROW LEVEL SECURITY;

CREATE POLICY message_company_isolation ON message USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX message_inbox_idx ON message(to_employee_id, read_at, created_at, id);
