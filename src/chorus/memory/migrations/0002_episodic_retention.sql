-- Migration 0002 — retention metadata for recall ranking (R2).
-- Rebuild episodic_record so sqlite_master DDL matches schema/episodic_record.sql (parity test).

PRAGMA legacy_alter_table=ON;

ALTER TABLE episodic_record RENAME TO episodic_record__old;

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
    recorded_at TEXT NOT NULL,
    files_touched TEXT NOT NULL DEFAULT '[]',
    pin_count   INTEGER NOT NULL DEFAULT 0,
    last_recalled_at TEXT,
    tier        TEXT NOT NULL DEFAULT 'hot'
);

INSERT INTO episodic_record (
    run_id, task_id, employee_id, scope, role, intent, outcome, score, body,
    artifacts, created_at, recorded_at, files_touched, pin_count, last_recalled_at, tier
)
SELECT
    run_id, task_id, employee_id, scope, role, intent, outcome, score, body,
    artifacts, created_at, recorded_at, files_touched, 0, NULL, 'hot'
FROM episodic_record__old;

DROP TABLE episodic_record__old;

CREATE INDEX episodic_record_employee_idx ON episodic_record(employee_id, recorded_at);
CREATE INDEX episodic_record_recall_idx ON episodic_record(employee_id, tier, recorded_at DESC);

PRAGMA legacy_alter_table=OFF;
