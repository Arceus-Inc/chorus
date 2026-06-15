-- Migration 0005 — approval (spec 01 Cluster G): the human gate.
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Declarative copy lives in ../schema/approval.sql; test_schema_parity asserts they agree.

CREATE TABLE approval (
    id                 TEXT PRIMARY KEY,
    subject_kind       TEXT NOT NULL,
    subject_id         TEXT NOT NULL,
    reason             TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending',
    decided_by_user_id TEXT,
    decided_at         TEXT,
    expires_at         TEXT,
    created_at         TEXT NOT NULL
);

-- exact-once gate: at most one pending approval per subject
CREATE UNIQUE INDEX approval_subject_pending_uq
    ON approval(subject_kind, subject_id) WHERE status = 'pending';
