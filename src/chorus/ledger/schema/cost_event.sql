-- Cluster E: cost_event (the immutable spend ledger). Declarative; applied via migrations/.
CREATE TABLE cost_event (
    id            TEXT PRIMARY KEY,
    employee_id   TEXT NOT NULL REFERENCES employee(id),
    task_id       TEXT REFERENCES task(id),
    run_id        TEXT REFERENCES run(id),
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_cents    INTEGER NOT NULL,
    occurred_at   TEXT NOT NULL
);

CREATE INDEX cost_event_employee_idx ON cost_event(employee_id, occurred_at);
