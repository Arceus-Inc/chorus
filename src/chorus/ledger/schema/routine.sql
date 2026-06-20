-- Cluster C: routine (cron template + owner + policies). Declarative; applied via migrations/.
CREATE TABLE routine (
    id                 TEXT PRIMARY KEY,
    employee_id        TEXT NOT NULL REFERENCES employee(id),
    goal_id            TEXT REFERENCES goal(id),
    parent_task_id     TEXT REFERENCES task(id),
    intent_template    TEXT NOT NULL,
    target             TEXT NOT NULL DEFAULT 'spawn_task',
    concurrency_policy TEXT NOT NULL DEFAULT 'coalesce',
    catch_up_policy    TEXT NOT NULL DEFAULT 'skip_missed',
    status             TEXT NOT NULL DEFAULT 'active',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
