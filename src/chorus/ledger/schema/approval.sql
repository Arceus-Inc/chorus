-- Cluster G: approval (the human gate). Declarative; applied via migrations/.
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

CREATE UNIQUE INDEX approval_subject_pending_uq
    ON approval(subject_kind, subject_id) WHERE status = 'pending';
