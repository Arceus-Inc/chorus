-- Migration 0002 — task_dependency (spec 01 Cluster A): the real DAG edge "A depends on B".
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Declarative copy lives in ../schema/task_dependency.sql; test_schema_parity asserts they agree.

CREATE TABLE task_dependency (
    id            TEXT PRIMARY KEY,
    task_id       TEXT NOT NULL REFERENCES task(id),
    depends_on_id TEXT NOT NULL REFERENCES task(id),
    created_at    TEXT NOT NULL,
    CONSTRAINT task_dependency_no_self CHECK (task_id <> depends_on_id)
);

-- one edge per (dependent, blocker); also serves task_id (leftmost-prefix) lookups
CREATE UNIQUE INDEX task_dependency_uq ON task_dependency(task_id, depends_on_id);

-- reverse lookup: who depends on a given blocker (for resolution wakes)
CREATE INDEX task_dependency_depends_on_idx ON task_dependency(depends_on_id);
