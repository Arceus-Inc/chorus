-- Migration 0015 — approval.action (spec 04 §5 governance — the generalized governed-action queue).
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Which governed action an approval is (hire_employee | plan_approval | board_approval |
-- budget_override | task_gate). The GovernanceResolver dispatches on it. Done by the rename-old
-- rebuild (CREATE the final table directly, not ALTER ADD COLUMN) so the stored DDL matches the
-- declarative schema/approval.sql (parity test, cf. migration 0014).
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
    gate_kind          TEXT,
    action             TEXT NOT NULL DEFAULT 'task_gate'
);

INSERT INTO approval (id, subject_kind, subject_id, reason, status, decided_by_user_id,
                      decided_at, expires_at, created_at, gate_kind, action)
    SELECT id, subject_kind, subject_id, reason, status, decided_by_user_id,
           decided_at, expires_at, created_at, gate_kind,
           CASE subject_kind WHEN 'budget_incident' THEN 'budget_override' ELSE 'task_gate' END
    FROM approval__old;

DROP TABLE approval__old;

CREATE UNIQUE INDEX approval_subject_pending_uq
    ON approval(subject_kind, subject_id) WHERE status = 'pending';

PRAGMA legacy_alter_table=OFF;
