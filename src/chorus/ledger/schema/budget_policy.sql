-- Cluster E: budget_policy (the spend cap). Declarative; applied via migrations/.
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
