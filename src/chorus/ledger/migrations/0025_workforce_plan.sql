-- Migration 0025 — governed workforce plan revisions and normalized proposal members.

CREATE TABLE workforce_plan (
    id                          TEXT NOT NULL,
    revision                    INTEGER NOT NULL,
    status                      TEXT NOT NULL,
    proposed_by_employee_id     TEXT NOT NULL REFERENCES employee(id),
    rationale                   TEXT NOT NULL,
    confidence                  REAL NOT NULL,
    source_goal_ids             TEXT NOT NULL DEFAULT '[]',
    revised_by_user_id          TEXT,
    decided_by_user_id          TEXT,
    created_at                  TEXT NOT NULL,
    decided_at                  TEXT,
    PRIMARY KEY (id, revision)
);

CREATE INDEX workforce_plan_status_idx ON workforce_plan(status, created_at);

CREATE TABLE workforce_plan_employee (
    plan_id                     TEXT NOT NULL,
    plan_revision               INTEGER NOT NULL,
    employee_ref                TEXT NOT NULL,
    name                        TEXT NOT NULL,
    profession                  TEXT NOT NULL,
    reports_to_ref              TEXT NOT NULL,
    responsibilities            TEXT NOT NULL DEFAULT '[]',
    budget_cents                INTEGER,
    PRIMARY KEY (plan_id, plan_revision, employee_ref),
    FOREIGN KEY (plan_id, plan_revision) REFERENCES workforce_plan(id, revision)
);

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