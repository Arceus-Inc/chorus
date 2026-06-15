-- Cluster F: artifact (the landed outcome). Declarative; applied via migrations/.
CREATE TABLE artifact (
    id            TEXT PRIMARY KEY,
    task_id       TEXT NOT NULL REFERENCES task(id),
    type          TEXT NOT NULL,
    provider      TEXT,
    external_id   TEXT,
    url           TEXT,
    review_state  TEXT,
    health_status TEXT,
    is_primary    INTEGER NOT NULL DEFAULT 0,
    resource_ref  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX artifact_task_idx ON artifact(task_id);
