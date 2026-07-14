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