-- Cluster F: dod (definition-of-done + verification record, 1:1 with task).
-- Declarative; applied via migrations/.
CREATE TABLE dod (
    id                 TEXT PRIMARY KEY,
    task_id            TEXT NOT NULL REFERENCES task(id),
    kind               TEXT NOT NULL,
    spec               TEXT NOT NULL DEFAULT '{}',
    artifact_class     TEXT,
    revision           INTEGER NOT NULL DEFAULT 1,
    status             TEXT NOT NULL DEFAULT 'pending',
    verdict            TEXT,
    verified_by_run_id TEXT REFERENCES run(id),
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE UNIQUE INDEX dod_task_uq ON dod(task_id);
CREATE INDEX dod_kind_idx ON dod(kind);
CREATE INDEX dod_status_idx ON dod(status);
