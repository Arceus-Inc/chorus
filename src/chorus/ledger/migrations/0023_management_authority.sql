-- Migration 0023 — M8 management profiles, Teams, memberships, and delegation contracts.

CREATE TABLE management_profile (
    employee_id             TEXT PRIMARY KEY REFERENCES employee(id),
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
    updated_at              TEXT NOT NULL
);

CREATE INDEX management_profile_active_idx ON management_profile(active);

CREATE TABLE team (
    id                      TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    lead_employee_id        TEXT NOT NULL REFERENCES employee(id),
    goal_id                 TEXT REFERENCES goal(id),
    parent_team_id          TEXT REFERENCES team(id),
    status                  TEXT NOT NULL DEFAULT 'forming',
    policy_version          INTEGER NOT NULL DEFAULT 1,
    created_by              TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    activated_at            TEXT,
    archived_at             TEXT
);

CREATE INDEX team_lead_status_idx ON team(lead_employee_id, status);
CREATE INDEX team_goal_idx ON team(goal_id);

CREATE TABLE team_member (
    team_id                 TEXT NOT NULL REFERENCES team(id),
    employee_id             TEXT NOT NULL REFERENCES employee(id),
    membership_role         TEXT NOT NULL DEFAULT 'member',
    can_subdelegate         INTEGER NOT NULL DEFAULT 0,
    source_manager_id       TEXT NOT NULL REFERENCES employee(id),
    joined_at               TEXT NOT NULL,
    left_at                 TEXT,
    PRIMARY KEY (team_id, employee_id)
);

CREATE INDEX team_member_employee_idx ON team_member(employee_id, left_at);

CREATE TABLE delegation_contract (
    task_id                    TEXT PRIMARY KEY REFERENCES task(id),
    team_id                    TEXT NOT NULL REFERENCES team(id),
    lead_employee_id           TEXT NOT NULL REFERENCES employee(id),
    management_profile_version INTEGER NOT NULL,
    parent_contract_task_id    TEXT REFERENCES delegation_contract(task_id),
    can_subdelegate            INTEGER NOT NULL DEFAULT 0,
    max_depth                  INTEGER NOT NULL DEFAULT 0,
    max_team_size              INTEGER NOT NULL DEFAULT 1,
    spend_limit_cents          INTEGER,
    objective_rubric           TEXT NOT NULL,
    status                     TEXT NOT NULL DEFAULT 'forming',
    accepted_run_id            TEXT,
    accepted_at                TEXT,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);

CREATE INDEX delegation_contract_team_status_idx ON delegation_contract(team_id, status);
CREATE INDEX delegation_contract_lead_status_idx ON delegation_contract(lead_employee_id, status);