-- Migration 0001 — episodic_record + record_file + record_fts (spec 07 §3-§6).
-- The append-only per-beat episodic capture: an immutable source row, its files_touched fan-out
-- (the fingerprint pre-filter), and an FTS5 index over intent+body (the BM25 half of retrieval).
-- Immutable once shipped: never edit; add a new numbered .sql instead.

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

CREATE TABLE record_file (
    run_id TEXT NOT NULL REFERENCES episodic_record(run_id),
    path   TEXT NOT NULL,
    PRIMARY KEY (run_id, path)
);

CREATE INDEX record_file_path_idx ON record_file(path);

CREATE VIRTUAL TABLE record_fts USING fts5(run_id UNINDEXED, intent, body);
