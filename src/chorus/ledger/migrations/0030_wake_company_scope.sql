-- Migration 0030 — wake carries the company discriminator (M5 shared-schema; spec 12 §6).
--
-- The coalesce unique key is company-scoped: coalesce keys hang off employee ids, which are
-- semantic slugs ("ace") unique only within a company. The column exists on BOTH engines because
-- the repo's ON CONFLICT target must name the same index columns everywhere; on SQLite the
-- single-org value is the degenerate '' (the Postgres rendering swaps in the tenancy GUC default).
--
-- Table rebuild (rename-aside) so the stored DDL matches the declarative schema/wake.sql exactly.

ALTER TABLE wake RENAME TO wake_old;
CREATE TABLE wake (
    id              TEXT PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employee(id),
    reason          TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'queued',
    coalesce_key    TEXT NOT NULL,
    coalesced_count INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    run_id          TEXT REFERENCES run(id),
    created_at      TEXT NOT NULL,
    claimed_at      TEXT,
    finished_at     TEXT,
    task_id         TEXT,
    company_id      TEXT NOT NULL DEFAULT ''
);
INSERT INTO wake (id, employee_id, reason, payload, status, coalesce_key, coalesced_count,
                  idempotency_key, run_id, created_at, claimed_at, finished_at, task_id)
    SELECT id, employee_id, reason, payload, status, coalesce_key, coalesced_count,
           idempotency_key, run_id, created_at, claimed_at, finished_at, task_id
    FROM wake_old;
DROP TABLE wake_old;
CREATE UNIQUE INDEX wake_queued_key_uq ON wake(company_id, coalesce_key) WHERE status = 'queued';
CREATE INDEX wake_employee_status_idx ON wake(employee_id, status);
CREATE INDEX wake_queue_idx ON wake(status, created_at, id)
