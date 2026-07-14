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