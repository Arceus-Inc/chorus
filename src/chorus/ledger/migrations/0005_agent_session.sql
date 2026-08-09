-- 0005_agent_session — chorus's pointer at each task's dream conversation.
-- dream owns the transcript in its own session store; this row maps
-- (employee, task) to the key that reopens it, and carries the parts chorus is
-- responsible for: spend, the last run to touch it, and why a resume failed.
-- Immutable once applied: author a new migration instead of editing this one.

CREATE TABLE agent_session (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                  uuid PRIMARY KEY,
    dream_session_key   text NOT NULL,
    employee_id         text NOT NULL,
    task_id             uuid NOT NULL REFERENCES task(id),
    run_id              uuid REFERENCES run(id),
    model               text NOT NULL DEFAULT '',
    -- Where the thread worked. dream refuses to resume a session into another
    -- directory, so chorus records the same fact to tell a mismatch from a
    -- missing session without asking.
    working_dir         text,
    -- Why the last resume failed (dream's SessionResumeError reason), cleared
    -- on the next clean beat.
    last_error          text,
    status              text NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'sealed', 'aborted')),
    cost                jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL,
    updated_at          timestamptz NOT NULL,
    FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE agent_session ENABLE ROW LEVEL SECURITY;

ALTER TABLE agent_session FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_session_company_isolation ON agent_session
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

-- One open session per task (Paperclip-style same-task resume).
CREATE UNIQUE INDEX agent_session_open_task_uq
    ON agent_session (company_id, task_id)
    WHERE status = 'open';

CREATE UNIQUE INDEX agent_session_dream_key_uq
    ON agent_session (company_id, dream_session_key);

CREATE INDEX agent_session_employee_updated_idx
    ON agent_session (company_id, employee_id, updated_at DESC);

CREATE INDEX agent_session_task_idx
    ON agent_session (company_id, task_id, updated_at DESC);
