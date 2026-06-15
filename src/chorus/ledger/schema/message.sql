-- Cluster G: message (the durable mailbox). Declarative; applied via migrations/.
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
    CONSTRAINT message_single_sender CHECK ((from_employee_id IS NULL) <> (from_user_id IS NULL))
);

CREATE INDEX message_inbox_idx ON message(to_employee_id, read_at, created_at, id);
