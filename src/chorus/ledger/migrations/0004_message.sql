-- Migration 0004 — message (spec 01 Cluster G): the durable mailbox.
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Declarative copy lives in ../schema/message.sql; test_schema_parity asserts they agree.

CREATE TABLE message (
    id               TEXT PRIMARY KEY,
    from_employee_id TEXT REFERENCES employee(id),
    from_user_id     TEXT,
    to_employee_id   TEXT NOT NULL REFERENCES employee(id),
    task_id          TEXT REFERENCES task(id),
    body             TEXT NOT NULL,
    kind             TEXT NOT NULL DEFAULT 'instruction',
    read_at          TEXT,
    created_at       TEXT NOT NULL,
    CONSTRAINT message_single_sender CHECK (from_employee_id IS NULL OR from_user_id IS NULL)
);

-- a recipient drains its unread inbox in one query
CREATE INDEX message_inbox_idx ON message(to_employee_id, read_at);
