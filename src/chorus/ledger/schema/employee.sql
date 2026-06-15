-- Cluster D: employee (the Workforce). Declarative; applied via migrations/.
CREATE TABLE employee (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    role                 TEXT NOT NULL,
    reports_to           TEXT REFERENCES employee(id),
    memory_scope         TEXT NOT NULL DEFAULT 'project',
    status               TEXT NOT NULL DEFAULT 'idle',
    budget_monthly_cents INTEGER NOT NULL DEFAULT 0,
    spent_monthly_cents  INTEGER NOT NULL DEFAULT 0,
    pause_reason         TEXT,
    paused_at            TEXT,
    last_beat_at         TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE INDEX employee_reports_to_idx ON employee(reports_to);
