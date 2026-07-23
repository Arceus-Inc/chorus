-- Migration 0001 — episodic_record + record_fts (spec 07 §3-§6).
-- Append-only per-beat capture: immutable source row (with inline files_touched metadata)
-- and an FTS5 index over intent+body (BM25 search). Immutable once shipped: add a new .sql instead.

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
    files_touched TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX episodic_record_employee_idx ON episodic_record(employee_id, recorded_at);

CREATE VIRTUAL TABLE record_fts USING fts5(run_id UNINDEXED, intent, body);
