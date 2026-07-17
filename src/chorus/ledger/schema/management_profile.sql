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

CREATE INDEX management_profile_active_idx ON management_profile(active);