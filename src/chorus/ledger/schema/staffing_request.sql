CREATE TABLE staffing_request (
    id                          TEXT PRIMARY KEY,
    task_id                     TEXT NOT NULL REFERENCES task(id),
    goal_id                     TEXT NOT NULL,
    team_id                     TEXT NOT NULL REFERENCES team(id),
    requested_by_employee_id    TEXT NOT NULL REFERENCES employee(id),
    rationale                   TEXT NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'open',
    workforce_plan_id           TEXT,
    created_at                  TEXT NOT NULL,
    resolved_at                 TEXT
);

CREATE INDEX staffing_request_status_idx ON staffing_request(status, created_at);