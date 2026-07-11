-- skill_revision: append-only full snapshots (mirrors routine_revision / Paperclip company_skill_versions).
CREATE TABLE skill_revision (
    id                          TEXT PRIMARY KEY,
    skill_id                    TEXT NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
    revision_no                 INTEGER NOT NULL,
    label                       TEXT,
    action                      TEXT NOT NULL,
    file_inventory              TEXT NOT NULL,
    content_hash                TEXT NOT NULL,
    source_run_ids              TEXT NOT NULL DEFAULT '[]',
    author_run_id               TEXT,
    restored_from_revision_id   TEXT REFERENCES skill_revision(id),
    created_at                  TEXT NOT NULL
);

CREATE UNIQUE INDEX skill_revision_no_uq ON skill_revision(skill_id, revision_no);
CREATE INDEX skill_revision_skill_created_idx ON skill_revision(skill_id, created_at);
