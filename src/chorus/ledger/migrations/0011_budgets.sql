-- Migration 0011 — budgets (spec 01 Cluster E): two-gate money.
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Declarative copies live in ../schema/{budget_policy,budget_incident,cost_event}.sql.

CREATE TABLE budget_policy (
    id                TEXT PRIMARY KEY,
    scope_type        TEXT NOT NULL,
    scope_id          TEXT NOT NULL,
    amount            INTEGER NOT NULL,
    metric            TEXT NOT NULL DEFAULT 'cost_cents',
    warn_percent      INTEGER NOT NULL DEFAULT 80,
    hard_stop_enabled INTEGER NOT NULL DEFAULT 1,
    window_kind       TEXT NOT NULL DEFAULT 'monthly',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE UNIQUE INDEX budget_policy_scope_uq
    ON budget_policy(scope_type, scope_id, metric, window_kind);

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

-- at most one live incident per policy/window/threshold (a dismissed one frees the window)
CREATE UNIQUE INDEX budget_incident_window_uq
    ON budget_incident(policy_id, window_start, threshold_type) WHERE status <> 'dismissed';

CREATE TABLE cost_event (
    id            TEXT PRIMARY KEY,
    employee_id   TEXT NOT NULL REFERENCES employee(id),
    task_id       TEXT REFERENCES task(id),
    run_id        TEXT REFERENCES run(id),
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_cents    INTEGER NOT NULL,
    occurred_at   TEXT NOT NULL
);

-- spend is recomputed live by summing cost_events per employee/window
CREATE INDEX cost_event_employee_idx ON cost_event(employee_id, occurred_at);
