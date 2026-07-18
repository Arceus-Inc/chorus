-- 0002_skills — the SkillStore leaves SQLite: skill HEAD + append-only skill_revision join
-- the shared engine schema (company_id + FORCE RLS, house pattern). The episodic-memory store
-- stays a workdir-local SQLite file by design — skills port alone because they are the one
-- store where the DB is the source of truth (evolved skills rematerialize from it every beat).
-- Immutable once applied: author a new migration instead of editing this one.

CREATE TABLE skill (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                   uuid PRIMARY KEY,
    employee_id          text NOT NULL,
    slug                 text NOT NULL,
    name                 text NOT NULL,
    description          text NOT NULL DEFAULT '',
    when_to_use          text NOT NULL DEFAULT '',
    origin               text NOT NULL,
    canonical_slug       text,
    latest_revision_id   uuid,
    latest_revision_no   integer NOT NULL DEFAULT 0,
    state                text NOT NULL DEFAULT 'active',
    patch_count          integer NOT NULL DEFAULT 0,
    last_patched_at      timestamptz,
    created_at           timestamptz NOT NULL,
    updated_at           timestamptz NOT NULL
);

ALTER TABLE skill ENABLE ROW LEVEL SECURITY;

ALTER TABLE skill FORCE ROW LEVEL SECURITY;

CREATE POLICY skill_company_isolation ON skill USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX skill_employee_slug_uq ON skill(company_id, employee_id, slug);

CREATE INDEX skill_employee_state_idx ON skill(company_id, employee_id, state);

CREATE TABLE skill_revision (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                          uuid PRIMARY KEY,
    skill_id                    uuid NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
    revision_no                 integer NOT NULL,
    label                       text,
    action                      text NOT NULL,
    file_inventory              text NOT NULL,
    content_hash                text NOT NULL,
    source_run_ids              jsonb NOT NULL DEFAULT '[]'::jsonb,
    author_run_id               uuid,
    restored_from_revision_id   uuid REFERENCES skill_revision(id),
    created_at                  timestamptz NOT NULL
);

ALTER TABLE skill_revision ENABLE ROW LEVEL SECURITY;

ALTER TABLE skill_revision FORCE ROW LEVEL SECURITY;

CREATE POLICY skill_revision_company_isolation ON skill_revision USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX skill_revision_no_uq ON skill_revision(skill_id, revision_no);

CREATE INDEX skill_revision_skill_created_idx ON skill_revision(skill_id, created_at);
