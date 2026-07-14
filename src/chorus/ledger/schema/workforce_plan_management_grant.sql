CREATE TABLE workforce_plan_management_grant (
    plan_id                     TEXT NOT NULL,
    plan_revision               INTEGER NOT NULL,
    employee_ref                TEXT NOT NULL,
    can_lead                    INTEGER NOT NULL DEFAULT 0,
    can_subdelegate             INTEGER NOT NULL DEFAULT 0,
    max_delegation_depth        INTEGER NOT NULL DEFAULT 0,
    max_team_size               INTEGER NOT NULL DEFAULT 1,
    allowed_professions         TEXT NOT NULL DEFAULT '[]',
    spend_limit_cents           INTEGER,
    PRIMARY KEY (plan_id, plan_revision, employee_ref),
    FOREIGN KEY (plan_id, plan_revision) REFERENCES workforce_plan(id, revision)
);