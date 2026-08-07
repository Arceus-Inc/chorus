-- 0005_agent_session — durable dream conversation + tool-call history in the ledger.
-- Beats must not keep the SoT in process memory or a local file: resume loads from here.
-- Immutable once applied: author a new migration instead of editing this one.

CREATE TABLE agent_session (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                  uuid PRIMARY KEY,
    dream_session_key   text NOT NULL,
    employee_id         text NOT NULL,
    task_id             uuid NOT NULL REFERENCES task(id),
    run_id              uuid REFERENCES run(id),
    model               text NOT NULL DEFAULT '',
    system_prompt       text,
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


CREATE TABLE conversation_message (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id           uuid PRIMARY KEY,
    session_id   uuid NOT NULL REFERENCES agent_session(id) ON DELETE CASCADE,
    seq          bigint NOT NULL,
    role         text NOT NULL CHECK (role IN ('user', 'assistant')),
    content      jsonb NOT NULL,
    created_at   timestamptz NOT NULL,
    CONSTRAINT conversation_message_seq_positive CHECK (seq > 0)
);

ALTER TABLE conversation_message ENABLE ROW LEVEL SECURITY;

ALTER TABLE conversation_message FORCE ROW LEVEL SECURITY;

CREATE POLICY conversation_message_company_isolation ON conversation_message
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX conversation_message_session_seq_uq
    ON conversation_message (session_id, seq);

-- Cursor pagination / resume load: equality on session_id, ordered by seq.
CREATE INDEX conversation_message_session_seq_idx
    ON conversation_message (session_id, seq);


CREATE TABLE tool_call (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id              uuid PRIMARY KEY,
    session_id      uuid NOT NULL REFERENCES agent_session(id) ON DELETE CASCADE,
    tool_use_id     text NOT NULL,
    tool_name       text NOT NULL,
    input           jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_content  text,
    is_error        boolean,
    created_at      timestamptz NOT NULL,
    completed_at    timestamptz
);

ALTER TABLE tool_call ENABLE ROW LEVEL SECURITY;

ALTER TABLE tool_call FORCE ROW LEVEL SECURITY;

CREATE POLICY tool_call_company_isolation ON tool_call
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX tool_call_session_use_uq
    ON tool_call (session_id, tool_use_id);

CREATE INDEX tool_call_session_created_idx
    ON tool_call (session_id, created_at, id);
