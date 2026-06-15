-- Cluster A: decomposition_claim (exact-once fan-out). Declarative; applied via migrations/.
CREATE TABLE decomposition_claim (
    id                        TEXT PRIMARY KEY,
    source_task_id            TEXT NOT NULL REFERENCES task(id),
    accepted_plan_revision_id TEXT NOT NULL REFERENCES artifact_revision(id),
    status                    TEXT NOT NULL DEFAULT 'in_flight',
    request_fingerprint       TEXT NOT NULL DEFAULT '',
    requested_children        TEXT NOT NULL DEFAULT '[]',
    child_task_ids            TEXT NOT NULL DEFAULT '[]',
    owner_run_id              TEXT REFERENCES run(id),
    completed_at              TEXT,
    created_at                TEXT NOT NULL
);

CREATE UNIQUE INDEX decomp_source_revision_uq
    ON decomposition_claim(source_task_id, accepted_plan_revision_id);

CREATE INDEX decomp_active_owner_idx ON decomposition_claim(owner_run_id)
    WHERE status = 'in_flight';
