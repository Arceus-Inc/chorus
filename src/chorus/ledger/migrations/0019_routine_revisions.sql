-- Migration 0019 — routine revisions (spec 13 §2 / M4 S2). A routine becomes versioned:
-- routine gains a head pointer (latest_revision_id / latest_revision_no), a secret-ref env binding,
-- and a stable reconcile key; routine_revision holds the immutable append-only history; routine_run
-- records the revision each firing pinned. Immutable once shipped: never edit; add a new numbered .sql.
--
-- routine and routine_run are rebuilt (rename-old, CREATE final shape directly — parity with
-- schema/*.sql, cf. migrations 0014–0018: "CREATE the final table directly, not ALTER ADD COLUMN").
-- routine is referenced by routine_trigger.routine_id and routine_run.routine_id; legacy_alter_table
-- keeps those FKs pointing at the rebuilt table across the rename.
--
-- The runner applies this with foreign_keys OFF (see MigrationRunner.apply), so the circular
-- routine <-> routine_revision reference and the insert ordering below are unconstrained. Existing
-- routines (none in a fresh DB; defensively, any seeded) are carried forward with a synthesized
-- revision 1 derived from their current definition (deterministic id 'rrev_seed_' || routine id).

PRAGMA legacy_alter_table=ON;

ALTER TABLE routine RENAME TO routine__old;

CREATE TABLE routine (
    id                 TEXT PRIMARY KEY,
    employee_id        TEXT NOT NULL REFERENCES employee(id),
    goal_id            TEXT REFERENCES goal(id),
    parent_task_id     TEXT REFERENCES task(id),
    intent_template    TEXT NOT NULL,
    target             TEXT NOT NULL DEFAULT 'spawn_task',
    concurrency_policy TEXT NOT NULL DEFAULT 'coalesce',
    catch_up_policy    TEXT NOT NULL DEFAULT 'skip_missed',
    status             TEXT NOT NULL DEFAULT 'active',
    env                TEXT,
    routine_key        TEXT,
    latest_revision_id TEXT REFERENCES routine_revision(id),
    latest_revision_no INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE routine_revision (
    id                        TEXT PRIMARY KEY,
    routine_id                TEXT NOT NULL REFERENCES routine(id),
    revision_no               INTEGER NOT NULL,
    intent_template           TEXT NOT NULL,
    target                    TEXT NOT NULL,
    concurrency_policy        TEXT NOT NULL,
    catch_up_policy           TEXT NOT NULL,
    env                       TEXT,
    change_summary            TEXT,
    restored_from_revision_id TEXT REFERENCES routine_revision(id),
    created_at                TEXT NOT NULL
);

INSERT INTO routine (id, employee_id, goal_id, parent_task_id, intent_template, target,
                     concurrency_policy, catch_up_policy, status, env, routine_key,
                     latest_revision_id, latest_revision_no, created_at, updated_at)
    SELECT id, employee_id, goal_id, parent_task_id, intent_template, target,
           concurrency_policy, catch_up_policy, status, NULL, NULL,
           NULL, 1, created_at, updated_at
    FROM routine__old;

INSERT INTO routine_revision (id, routine_id, revision_no, intent_template, target,
                              concurrency_policy, catch_up_policy, env, change_summary,
                              restored_from_revision_id, created_at)
    SELECT 'rrev_seed_' || id, id, 1, intent_template, target,
           concurrency_policy, catch_up_policy, NULL, 'synthesized from pre-revision routine',
           NULL, created_at
    FROM routine__old;

UPDATE routine SET latest_revision_id = 'rrev_seed_' || id;

DROP TABLE routine__old;

CREATE UNIQUE INDEX routine_employee_key_uq ON routine(employee_id, routine_key)
    WHERE routine_key IS NOT NULL;

CREATE UNIQUE INDEX routine_revision_no_uq ON routine_revision(routine_id, revision_no);

ALTER TABLE routine_run RENAME TO routine_run__old;

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

INSERT INTO routine_run (id, routine_id, trigger_id, status, dispatch_fingerprint,
                         idempotency_key, linked_task_id, coalesced_into_run_id,
                         routine_revision_id, created_at)
    SELECT id, routine_id, trigger_id, status, dispatch_fingerprint,
           idempotency_key, linked_task_id, coalesced_into_run_id,
           NULL, created_at
    FROM routine_run__old;

DROP TABLE routine_run__old;

CREATE UNIQUE INDEX routine_run_idempotency_uq ON routine_run(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

PRAGMA legacy_alter_table=OFF;
