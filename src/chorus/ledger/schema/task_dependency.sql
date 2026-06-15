-- Cluster A: task_dependency (the real DAG edge "A depends on B"). Declarative; applied via migrations/.
CREATE TABLE task_dependency (
    id            TEXT PRIMARY KEY,
    task_id       TEXT NOT NULL REFERENCES task(id),
    depends_on_id TEXT NOT NULL REFERENCES task(id),
    created_at    TEXT NOT NULL,
    CONSTRAINT task_dependency_no_self CHECK (task_id <> depends_on_id)
);

CREATE UNIQUE INDEX task_dependency_uq ON task_dependency(task_id, depends_on_id);
CREATE INDEX task_dependency_depends_on_idx ON task_dependency(depends_on_id);
