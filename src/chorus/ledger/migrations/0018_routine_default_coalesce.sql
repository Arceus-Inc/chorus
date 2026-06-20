-- Migration 0018 — flip routine.concurrency_policy default 'skip_if_active' → 'coalesce'
-- (spec 13 §1 / M4 S1: safe-by-default — a re-firing folds onto the live run instead of being
-- dropped, and firings stay recorded). Immutable once shipped: never edit; add a new numbered .sql.
-- SQLite can't ALTER a column default in place, so this is the rename-old rebuild (CREATE the final
-- table directly, parity with schema/routine.sql, cf. migrations 0014–0017). routine is referenced by
-- routine_trigger.routine_id and routine_run.routine_id; legacy_alter_table keeps those FKs pointing
-- at the rebuilt table across the rename.

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
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

INSERT INTO routine (id, employee_id, goal_id, parent_task_id, intent_template, target,
                     concurrency_policy, catch_up_policy, status, created_at, updated_at)
    SELECT id, employee_id, goal_id, parent_task_id, intent_template, target,
           concurrency_policy, catch_up_policy, status, created_at, updated_at
    FROM routine__old;

DROP TABLE routine__old;

PRAGMA legacy_alter_table=OFF;
