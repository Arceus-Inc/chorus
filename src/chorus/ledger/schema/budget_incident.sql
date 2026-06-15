-- Cluster E: budget_incident (a breach record). Declarative; applied via migrations/.
CREATE TABLE budget_incident (
    id              TEXT PRIMARY KEY,
    policy_id       TEXT NOT NULL REFERENCES budget_policy(id),
    threshold_type  TEXT NOT NULL,
    amount_limit    INTEGER NOT NULL,
    amount_observed INTEGER NOT NULL,
    window_start    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',
    approval_id     TEXT REFERENCES approval(id),
    created_at      TEXT NOT NULL
);

CREATE UNIQUE INDEX budget_incident_window_uq
    ON budget_incident(policy_id, window_start, threshold_type) WHERE status <> 'dismissed';
