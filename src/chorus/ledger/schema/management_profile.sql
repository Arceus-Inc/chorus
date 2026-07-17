-- management_profile — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE management_profile (
    employee_id             text NOT NULL,
    active                  boolean NOT NULL DEFAULT false,
    can_lead                boolean NOT NULL DEFAULT false,
    can_subdelegate         boolean NOT NULL DEFAULT false,
    max_delegation_depth    integer NOT NULL DEFAULT 0,
    max_team_size           integer NOT NULL DEFAULT 1,
    allowed_professions     jsonb NOT NULL DEFAULT '[]',
    spend_limit_cents       bigint,
    version                 integer NOT NULL DEFAULT 1,
    granted_by_user_id      text NOT NULL,
    created_at              timestamptz NOT NULL,
    updated_at              timestamptz NOT NULL,
    company_id              uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    PRIMARY KEY (company_id, employee_id),
    FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE management_profile ENABLE ROW LEVEL SECURITY;

ALTER TABLE management_profile FORCE ROW LEVEL SECURITY;

CREATE POLICY management_profile_company_isolation ON management_profile USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX management_profile_active_idx ON management_profile(active);
