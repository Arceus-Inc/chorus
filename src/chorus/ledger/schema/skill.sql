-- skill — Postgres-native (uuid/timestamptz/jsonb; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.
-- Skill HEAD (chorus-owned procedural memory). Slugs are per-employee within a company, so the
-- unique key is company-prefixed — the id itself is a minted uuid and stays globally unique.

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
