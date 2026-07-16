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