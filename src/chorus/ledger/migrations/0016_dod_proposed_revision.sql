-- Migration 0016 — dod.proposed_revision (spec 04 §1 DoD revisability).
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- A *loosen* revision awaiting §5 approval is staged here as JSON {kind, spec, artifact_class}; the
-- in-force verifier (the kind/spec/artifact_class columns) stays put until the loosen_dod gate is
-- granted, at which point the staged verifier is promoted and this column cleared. NULL otherwise.
-- Done by the rename-old rebuild (CREATE the final table directly, not ALTER ADD COLUMN) so the
-- stored DDL matches the declarative schema/dod.sql (parity test, cf. migrations 0014/0015).
-- dod references task(id) and run(id); legacy_alter_table keeps those FKs pointing at the live tables
-- (not dod__old) across the rename.

PRAGMA legacy_alter_table=ON;

ALTER TABLE dod RENAME TO dod__old;

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
    updated_at         TEXT NOT NULL,
    proposed_revision  TEXT
);

INSERT INTO dod (id, task_id, kind, spec, artifact_class, revision, status, verdict,
                 verified_by_run_id, created_at, updated_at, proposed_revision)
    SELECT id, task_id, kind, spec, artifact_class, revision, status, verdict,
           verified_by_run_id, created_at, updated_at, NULL
    FROM dod__old;

DROP TABLE dod__old;

CREATE UNIQUE INDEX dod_task_uq ON dod(task_id);
CREATE INDEX dod_kind_idx ON dod(kind);
CREATE INDEX dod_status_idx ON dod(status);

PRAGMA legacy_alter_table=OFF;
