-- Migration 0031 — management_profile carries the company discriminator (M5 shared-schema).
--
-- Its upsert names the primary key as an ON CONFLICT target, so the conflict spec must match the
-- same index columns on BOTH engines: PRIMARY KEY (company_id, employee_id). SQLite's single-org
-- value is the degenerate '' (the Postgres rendering swaps in the tenancy GUC default) — the same
-- treatment wake got in 0030.
--
-- Table rebuild (rename-aside) so the stored DDL matches the declarative schema file exactly.

ALTER TABLE management_profile RENAME TO management_profile_old;
CREATE TABLE management_profile (
    employee_id             TEXT NOT NULL REFERENCES employee(id),
    active                  INTEGER NOT NULL DEFAULT 0,
    can_lead                INTEGER NOT NULL DEFAULT 0,
    can_subdelegate         INTEGER NOT NULL DEFAULT 0,
    max_delegation_depth    INTEGER NOT NULL DEFAULT 0,
    max_team_size           INTEGER NOT NULL DEFAULT 1,
    allowed_professions     TEXT NOT NULL DEFAULT '[]',
    spend_limit_cents       INTEGER,
    version                 INTEGER NOT NULL DEFAULT 1,
    granted_by_user_id      TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    company_id              TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (company_id, employee_id)
);
INSERT INTO management_profile (employee_id, active, can_lead, can_subdelegate,
                                max_delegation_depth, max_team_size, allowed_professions,
                                spend_limit_cents, version, granted_by_user_id, created_at,
                                updated_at)
    SELECT employee_id, active, can_lead, can_subdelegate, max_delegation_depth, max_team_size,
           allowed_professions, spend_limit_cents, version, granted_by_user_id, created_at,
           updated_at
    FROM management_profile_old;
DROP TABLE management_profile_old;
CREATE INDEX management_profile_active_idx ON management_profile(active)
