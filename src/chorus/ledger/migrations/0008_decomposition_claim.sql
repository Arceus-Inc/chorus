-- Migration 0008 — decomposition_claim (spec 01 Cluster A): exact-once fan-out.
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Declarative copy lives in ../schema/decomposition_claim.sql; test_schema_parity asserts agreement.

CREATE TABLE decomposition_claim (
    id                        TEXT PRIMARY KEY,
    source_task_id            TEXT NOT NULL REFERENCES task(id),
    accepted_plan_revision_id TEXT NOT NULL REFERENCES artifact_revision(id),
    status                    TEXT NOT NULL DEFAULT 'in_flight',
    request_fingerprint       TEXT NOT NULL DEFAULT '',
    requested_children        TEXT NOT NULL DEFAULT '[]',
    child_task_ids            TEXT NOT NULL DEFAULT '[]',
    owner_run_id              TEXT,
    completed_at              TEXT,
    created_at                TEXT NOT NULL
);

-- THE canonical fingerprint: re-reading the same accepted plan can't authorize a 2nd child tree
CREATE UNIQUE INDEX decomp_source_revision_uq
    ON decomposition_claim(source_task_id, accepted_plan_revision_id);

CREATE INDEX decomp_active_owner_idx ON decomposition_claim(owner_run_id)
    WHERE status = 'in_flight';
