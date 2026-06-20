-- Cluster C: routine_revision (immutable, append-only history of a routine's definition).
-- The live routine row points at the head (routine.latest_revision_id); a routine_run pins the
-- revision it fired under so an edit never re-judges a firing in flight. Declarative; applied via migrations/.
CREATE TABLE routine_revision (
    id                        TEXT PRIMARY KEY,
    routine_id                TEXT NOT NULL REFERENCES routine(id),
    revision_no               INTEGER NOT NULL,
    intent_template           TEXT NOT NULL,
    target                    TEXT NOT NULL,
    concurrency_policy        TEXT NOT NULL,
    catch_up_policy           TEXT NOT NULL,
    env                       TEXT,
    change_summary            TEXT,
    restored_from_revision_id TEXT REFERENCES routine_revision(id),
    created_at                TEXT NOT NULL
);

CREATE UNIQUE INDEX routine_revision_no_uq ON routine_revision(routine_id, revision_no);
