-- Skills store foundation: skill HEAD + append-only skill_revision.
-- Chorus-owned procedural memory (not Lattice). Pattern: routine_revision / Paperclip versions.

CREATE TABLE skill (
    id                   TEXT PRIMARY KEY,
    employee_id          TEXT NOT NULL,
    slug                 TEXT NOT NULL,
    name                 TEXT NOT NULL,
    description          TEXT NOT NULL DEFAULT '',
    when_to_use          TEXT NOT NULL DEFAULT '',
    origin               TEXT NOT NULL,
    canonical_slug       TEXT,
    latest_revision_id   TEXT,
    latest_revision_no   INTEGER NOT NULL DEFAULT 0,
    state                TEXT NOT NULL DEFAULT 'active',
    patch_count          INTEGER NOT NULL DEFAULT 0,
    last_patched_at      TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE UNIQUE INDEX skill_employee_slug_uq ON skill(employee_id, slug);
CREATE INDEX skill_employee_state_idx ON skill(employee_id, state);

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
