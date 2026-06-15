-- Migration 0007 — artifact_revision (spec 01 Cluster F): immutable artifact history.
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Declarative copy lives in ../schema/artifact_revision.sql; test_schema_parity asserts they agree.

CREATE TABLE artifact_revision (
    id                TEXT PRIMARY KEY,
    artifact_id       TEXT NOT NULL REFERENCES artifact(id),
    revision          INTEGER NOT NULL,
    resource_ref      TEXT,
    summary           TEXT,
    created_by_run_id TEXT REFERENCES run(id),
    created_at        TEXT NOT NULL
);

-- one row per revision number per artifact; the (artifact, revision) pair is the stable history key
CREATE UNIQUE INDEX artifact_revision_seq_uq ON artifact_revision(artifact_id, revision);
