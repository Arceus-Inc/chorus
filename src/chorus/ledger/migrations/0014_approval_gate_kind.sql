-- Migration 0014 — approval.gate_kind (spec 04 §5 governance resolver).
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- How resolving a *task* approval acts on the task (acceptance | authorization); NULL for non-task
-- gates. Done by the rename-old rebuild (CREATE the final table directly, not ALTER ADD COLUMN) so
-- the stored DDL matches the declarative schema/approval.sql (parity test, cf. migration 0013).
-- approval is referenced by budget_incident.approval_id; legacy_alter_table stops the rename from
-- rewriting that FK to point at approval__old, so it correctly lands on the rebuilt table.

PRAGMA legacy_alter_table=ON;

ALTER TABLE approval RENAME TO approval__old;

CREATE TABLE approval (
    id                 TEXT PRIMARY KEY,
    subject_kind       TEXT NOT NULL,
    subject_id         TEXT NOT NULL,
    reason             TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending',
    decided_by_user_id TEXT,
    decided_at         TEXT,
    expires_at         TEXT,
    created_at         TEXT NOT NULL,
    gate_kind          TEXT
);

INSERT INTO approval (id, subject_kind, subject_id, reason, status, decided_by_user_id,
                      decided_at, expires_at, created_at)
    SELECT id, subject_kind, subject_id, reason, status, decided_by_user_id,
           decided_at, expires_at, created_at
    FROM approval__old;

DROP TABLE approval__old;

CREATE UNIQUE INDEX approval_subject_pending_uq
    ON approval(subject_kind, subject_id) WHERE status = 'pending';

PRAGMA legacy_alter_table=OFF;
