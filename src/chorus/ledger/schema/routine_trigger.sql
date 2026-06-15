-- Cluster C: routine_trigger (the schedule). Declarative; applied via migrations/.
CREATE TABLE routine_trigger (
    id              TEXT PRIMARY KEY,
    routine_id      TEXT NOT NULL REFERENCES routine(id),
    kind            TEXT NOT NULL DEFAULT 'cron',
    cron_expression TEXT,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    next_run_at     TEXT,
    last_fired_at   TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX routine_trigger_next_run_idx ON routine_trigger(next_run_at);
