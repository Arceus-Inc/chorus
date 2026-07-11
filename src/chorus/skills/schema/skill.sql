-- skill: employee-scoped procedural memory HEAD (Chorus-owned; Paperclip company_skills analogue).
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
    created_by           TEXT,
    curation_eligible    INTEGER NOT NULL DEFAULT 0,
    use_count            INTEGER NOT NULL DEFAULT 0,
    view_count           INTEGER NOT NULL DEFAULT 0,
    patch_count          INTEGER NOT NULL DEFAULT 0,
    last_used_at         TEXT,
    last_patched_at      TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE UNIQUE INDEX skill_employee_slug_uq ON skill(employee_id, slug);
CREATE INDEX skill_employee_state_idx ON skill(employee_id, state);
