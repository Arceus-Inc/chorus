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
    staffing_request_id         TEXT REFERENCES staffing_request(id),
    PRIMARY KEY (id, revision)
);

CREATE INDEX workforce_plan_status_idx ON workforce_plan(status, created_at);