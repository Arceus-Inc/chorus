-- Cluster C: run (one beat — THIN; liveness is witnessed). Declarative; applied via migrations/.
CREATE TABLE run (
    id                   TEXT PRIMARY KEY,
    employee_id          TEXT NOT NULL REFERENCES employee(id),
    task_id              TEXT NOT NULL REFERENCES task(id),
    wake_id              TEXT,
    status               TEXT NOT NULL DEFAULT 'queued',
    lease_expires_at     TEXT,
    liveness_state       TEXT,
    continuation_attempt INTEGER NOT NULL DEFAULT 0,
    outcome              TEXT NOT NULL DEFAULT '{}',
    usage                TEXT NOT NULL DEFAULT '{}',
    started_at           TEXT,
    finished_at          TEXT,
    created_at           TEXT NOT NULL,
    principal_kind       TEXT NOT NULL DEFAULT 'employee'
                         CHECK (principal_kind IN ('employee', 'system')),
    system_principal_id  TEXT REFERENCES system_principal(id)
                         CHECK (
                             (principal_kind = 'employee' AND system_principal_id IS NULL)
                             OR (principal_kind = 'system' AND system_principal_id IS NOT NULL)
                         )
);

CREATE INDEX run_employee_started_idx ON run(employee_id, started_at);
CREATE INDEX run_status_lease_idx ON run(status, lease_expires_at);
CREATE INDEX run_system_principal_idx ON run(system_principal_id, started_at);
