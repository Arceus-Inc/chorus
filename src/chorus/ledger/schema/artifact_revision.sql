-- Cluster F: artifact_revision (immutable artifact history). Declarative; applied via migrations/.
CREATE TABLE artifact_revision (
    id                TEXT PRIMARY KEY,
    artifact_id       TEXT NOT NULL REFERENCES artifact(id),
    revision          INTEGER NOT NULL,
    resource_ref      TEXT,
    summary           TEXT,
    created_by_run_id TEXT REFERENCES run(id),
    created_at        TEXT NOT NULL
);

CREATE UNIQUE INDEX artifact_revision_seq_uq ON artifact_revision(artifact_id, revision);
