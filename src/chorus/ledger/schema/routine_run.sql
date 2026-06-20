-- Cluster C: routine_run (one firing -> one task). Declarative; applied via migrations/.
-- routine_revision_id pins the routine definition this firing fired under (spec 13 §2.3).
CREATE TABLE routine_run (
    id                    TEXT PRIMARY KEY,
    routine_id            TEXT NOT NULL REFERENCES routine(id),
    trigger_id            TEXT NOT NULL REFERENCES routine_trigger(id),
    status                TEXT NOT NULL DEFAULT 'received',
    dispatch_fingerprint  TEXT NOT NULL DEFAULT '',
    idempotency_key       TEXT,
    linked_task_id        TEXT REFERENCES task(id),
    coalesced_into_run_id TEXT,
    routine_revision_id   TEXT REFERENCES routine_revision(id),
    created_at            TEXT NOT NULL
);

CREATE UNIQUE INDEX routine_run_idempotency_uq ON routine_run(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
