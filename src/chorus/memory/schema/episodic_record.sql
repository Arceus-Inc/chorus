-- The immutable per-beat episodic source row (spec 07 §3). Declarative; applied via migrations/.
CREATE TABLE episodic_record (
    run_id      TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'project',
    role        TEXT NOT NULL DEFAULT '',
    intent      TEXT NOT NULL DEFAULT '',
    outcome     TEXT NOT NULL DEFAULT '',
    score       REAL NOT NULL DEFAULT 0,
    body        TEXT NOT NULL DEFAULT '',
    artifacts   TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX episodic_record_employee_idx ON episodic_record(employee_id, recorded_at);
