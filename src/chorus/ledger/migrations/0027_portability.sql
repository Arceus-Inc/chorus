-- Migration 0027 — portability: explicit columns replace SQLite-only constructs (spec 12 §4).
--
-- wake.task_id: the dispatch-order join previously used json_extract(payload, '$.task_id') —
-- SQLite json1, no Postgres equivalent in the intersection. The task link becomes a real column,
-- stamped at enqueue and backfilled here.
--
-- workforce_plan_employee/grant.position: draft order previously leaned on rowid (SQLite's
-- physical row id; Postgres has none). Insertion order becomes explicit data.
--
-- Table rebuilds (not ALTER ADD) so the stored DDL matches the declarative schema/ files exactly
-- (the parity test compares normalised sqlite_master SQL). The runner executes this with FK
-- enforcement off, so the drop+rename never rewrites incoming references.

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
    task_id         TEXT
);
INSERT INTO wake (id, employee_id, reason, payload, status, coalesce_key, coalesced_count,
                      idempotency_key, run_id, created_at, claimed_at, finished_at, task_id)
    SELECT id, employee_id, reason, payload, status, coalesce_key, coalesced_count,
           idempotency_key, run_id, created_at, claimed_at, finished_at,
           json_extract(payload, '$.task_id')
    FROM wake_old;
DROP TABLE wake_old;
CREATE UNIQUE INDEX wake_queued_key_uq ON wake(coalesce_key) WHERE status = 'queued';
CREATE INDEX wake_employee_status_idx ON wake(employee_id, status);
CREATE INDEX wake_queue_idx ON wake(status, created_at, id);

ALTER TABLE workforce_plan_employee RENAME TO workforce_plan_employee_old;
CREATE TABLE workforce_plan_employee (
    plan_id                     TEXT NOT NULL,
    plan_revision               INTEGER NOT NULL,
    employee_ref                TEXT NOT NULL,
    name                        TEXT NOT NULL,
    profession                  TEXT NOT NULL,
    reports_to_ref              TEXT NOT NULL,
    responsibilities            TEXT NOT NULL DEFAULT '[]',
    budget_cents                INTEGER,
    position                    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (plan_id, plan_revision, employee_ref),
    FOREIGN KEY (plan_id, plan_revision) REFERENCES workforce_plan(id, revision)
);
INSERT INTO workforce_plan_employee (plan_id, plan_revision, employee_ref, name, profession,
                                         reports_to_ref, responsibilities, budget_cents, position)
    SELECT plan_id, plan_revision, employee_ref, name, profession, reports_to_ref,
           responsibilities, budget_cents,
           (SELECT COUNT(*) FROM workforce_plan_employee_old w2
            WHERE w2.plan_id = w.plan_id AND w2.plan_revision = w.plan_revision
              AND w2.rowid < w.rowid)
    FROM workforce_plan_employee_old w;
DROP TABLE workforce_plan_employee_old;

ALTER TABLE workforce_plan_management_grant RENAME TO workforce_plan_management_grant_old;
CREATE TABLE workforce_plan_management_grant (
    plan_id                     TEXT NOT NULL,
    plan_revision               INTEGER NOT NULL,
    employee_ref                TEXT NOT NULL,
    can_lead                    INTEGER NOT NULL DEFAULT 0,
    can_subdelegate             INTEGER NOT NULL DEFAULT 0,
    max_delegation_depth        INTEGER NOT NULL DEFAULT 0,
    max_team_size               INTEGER NOT NULL DEFAULT 1,
    allowed_professions         TEXT NOT NULL DEFAULT '[]',
    spend_limit_cents           INTEGER,
    position                    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (plan_id, plan_revision, employee_ref),
    FOREIGN KEY (plan_id, plan_revision) REFERENCES workforce_plan(id, revision)
);
INSERT INTO workforce_plan_management_grant (plan_id, plan_revision, employee_ref, can_lead,
                                                 can_subdelegate, max_delegation_depth,
                                                 max_team_size, allowed_professions,
                                                 spend_limit_cents, position)
    SELECT plan_id, plan_revision, employee_ref, can_lead, can_subdelegate, max_delegation_depth,
           max_team_size, allowed_professions, spend_limit_cents,
           (SELECT COUNT(*) FROM workforce_plan_management_grant_old g2
            WHERE g2.plan_id = g.plan_id AND g2.plan_revision = g.plan_revision
              AND g2.rowid < g.rowid)
    FROM workforce_plan_management_grant_old g;
DROP TABLE workforce_plan_management_grant_old
