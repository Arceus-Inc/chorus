-- skill_revision — Postgres-native (uuid/timestamptz/jsonb; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.
-- Append-only revision history under a skill HEAD. file_inventory stays text, not jsonb:
-- content_hash is sha256 over the exact canonical JSON bytes, and jsonb round-trips reformat.

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
