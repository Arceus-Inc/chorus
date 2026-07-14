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