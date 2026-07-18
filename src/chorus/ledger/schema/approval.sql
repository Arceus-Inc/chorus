-- approval — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE approval (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                 uuid PRIMARY KEY,
    subject_kind       text NOT NULL,
    subject_id         text NOT NULL,
    reason             text NOT NULL,
    status             text NOT NULL DEFAULT 'pending',
    decided_by_user_id text,
    decided_at         timestamptz,
    expires_at         timestamptz,
    created_at         timestamptz NOT NULL,
    gate_kind          text,
    action             text NOT NULL DEFAULT 'task_gate'
);

ALTER TABLE approval ENABLE ROW LEVEL SECURITY;

ALTER TABLE approval FORCE ROW LEVEL SECURITY;

CREATE POLICY approval_company_isolation ON approval USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX approval_subject_pending_uq
    ON approval(subject_kind, subject_id) WHERE status = 'pending';
