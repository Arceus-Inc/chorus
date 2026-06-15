-- Migration 0013 — review hardening (codeant consolidation): DB-level invariants + queue indexes.
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Adds defense-in-depth CHECK/FK constraints the repos already enforce, plus access-pattern indexes.
-- Constraints are added by the rename-old rebuild (CREATE the final table directly, not RENAME into
-- place) so the stored DDL stays unquoted and matches the declarative schema/ files (parity test).

-- --- access-pattern indexes (no table rebuild) ---------------------------------------------------

-- hot queue reads claim/list by status ordered by (created_at, id)
CREATE INDEX wake_queue_idx ON wake(status, created_at, id);

-- by_subject filters on (subject_kind, subject_id) and orders by (occurred_at, id)
DROP INDEX activity_subject_idx;
CREATE INDEX activity_subject_idx ON activity(subject_kind, subject_id, occurred_at, id);

-- --- message: exactly-one-sender XOR + covering inbox index --------------------------------------

ALTER TABLE message RENAME TO message__old;
CREATE TABLE message (
    id               TEXT PRIMARY KEY,
    from_employee_id TEXT REFERENCES employee(id),
    from_user_id     TEXT,
    to_employee_id   TEXT NOT NULL REFERENCES employee(id),
    task_id          TEXT REFERENCES task(id),
    body             TEXT NOT NULL,
    kind             TEXT NOT NULL DEFAULT 'instruction',
    read_at          TEXT,
    created_at       TEXT NOT NULL,
    CONSTRAINT message_single_sender CHECK ((from_employee_id IS NULL) <> (from_user_id IS NULL))
);
INSERT INTO message (id, from_employee_id, from_user_id, to_employee_id, task_id, body, kind,
    read_at, created_at)
    SELECT id, from_employee_id, from_user_id, to_employee_id, task_id, body, kind, read_at,
        created_at FROM message__old;
DROP TABLE message__old;
CREATE INDEX message_inbox_idx ON message(to_employee_id, read_at, created_at, id);

-- --- cost_event: non-negative spend (budget-bypass guard) ----------------------------------------

ALTER TABLE cost_event RENAME TO cost_event__old;
CREATE TABLE cost_event (
    id            TEXT PRIMARY KEY,
    employee_id   TEXT NOT NULL REFERENCES employee(id),
    task_id       TEXT REFERENCES task(id),
    run_id        TEXT REFERENCES run(id),
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_cents    INTEGER NOT NULL,
    occurred_at   TEXT NOT NULL,
    CONSTRAINT cost_event_nonneg CHECK (cost_cents >= 0 AND input_tokens >= 0 AND output_tokens >= 0)
);
INSERT INTO cost_event (id, employee_id, task_id, run_id, provider, model, input_tokens,
    output_tokens, cost_cents, occurred_at)
    SELECT id, employee_id, task_id, run_id, provider, model, input_tokens, output_tokens,
        cost_cents, occurred_at FROM cost_event__old;
DROP TABLE cost_event__old;
CREATE INDEX cost_event_employee_idx ON cost_event(employee_id, occurred_at);

-- --- monitor: armed rows need a schedule + bounded attempts --------------------------------------

ALTER TABLE monitor RENAME TO monitor__old;
CREATE TABLE monitor (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES task(id),
    employee_id     TEXT NOT NULL REFERENCES employee(id),
    next_check_at   TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    notes           TEXT,
    external_ref    TEXT,
    timeout_at      TEXT,
    max_attempts    INTEGER NOT NULL DEFAULT 1,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    recovery_policy TEXT NOT NULL DEFAULT 'wake_owner',
    created_at      TEXT NOT NULL,
    fired_at        TEXT,
    CONSTRAINT monitor_armed_has_schedule CHECK (status <> 'pending' OR next_check_at IS NOT NULL),
    CONSTRAINT monitor_attempts CHECK (
        attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts)
);
INSERT INTO monitor (id, task_id, employee_id, next_check_at, status, notes, external_ref,
    timeout_at, max_attempts, attempt_count, recovery_policy, created_at, fired_at)
    SELECT id, task_id, employee_id, next_check_at, status, notes, external_ref, timeout_at,
        max_attempts, attempt_count, recovery_policy, created_at, fired_at FROM monitor__old;
DROP TABLE monitor__old;
CREATE UNIQUE INDEX monitor_armed_task_uq ON monitor(task_id) WHERE status = 'pending';
CREATE INDEX monitor_due_idx ON monitor(next_check_at) WHERE status = 'pending';

-- --- recovery_action: bounded attempt counters --------------------------------------------------

ALTER TABLE recovery_action RENAME TO recovery_action__old;
CREATE TABLE recovery_action (
    id                         TEXT PRIMARY KEY,
    source_task_id             TEXT NOT NULL REFERENCES task(id),
    recovery_task_id           TEXT REFERENCES task(id),
    kind                       TEXT NOT NULL,
    status                     TEXT NOT NULL DEFAULT 'active',
    owner_employee_id          TEXT REFERENCES employee(id),
    owner_user_id              TEXT,
    previous_owner_employee_id TEXT REFERENCES employee(id),
    return_owner_employee_id   TEXT REFERENCES employee(id),
    cause                      TEXT NOT NULL DEFAULT '',
    fingerprint                TEXT NOT NULL DEFAULT '',
    evidence                   TEXT NOT NULL DEFAULT '{}',
    next_action                TEXT,
    wake_policy                TEXT NOT NULL DEFAULT '{}',
    monitor_policy             TEXT NOT NULL DEFAULT '{}',
    attempt_count              INTEGER NOT NULL DEFAULT 0,
    max_attempts               INTEGER NOT NULL DEFAULT 0,
    timeout_at                 TEXT,
    last_attempt_at            TEXT,
    resolved_at                TEXT,
    outcome                    TEXT,
    resolution_note            TEXT,
    created_at                 TEXT NOT NULL,
    CONSTRAINT recovery_attempts CHECK (
        attempt_count >= 0 AND max_attempts >= 0 AND attempt_count <= max_attempts)
);
INSERT INTO recovery_action (id, source_task_id, recovery_task_id, kind, status, owner_employee_id,
    owner_user_id, previous_owner_employee_id, return_owner_employee_id, cause, fingerprint,
    evidence, next_action, wake_policy, monitor_policy, attempt_count, max_attempts, timeout_at,
    last_attempt_at, resolved_at, outcome, resolution_note, created_at)
    SELECT id, source_task_id, recovery_task_id, kind, status, owner_employee_id, owner_user_id,
        previous_owner_employee_id, return_owner_employee_id, cause, fingerprint, evidence,
        next_action, wake_policy, monitor_policy, attempt_count, max_attempts, timeout_at,
        last_attempt_at, resolved_at, outcome, resolution_note, created_at FROM recovery_action__old;
DROP TABLE recovery_action__old;
CREATE UNIQUE INDEX recovery_active_source_uq ON recovery_action(source_task_id)
    WHERE status IN ('active', 'escalated');
CREATE UNIQUE INDEX recovery_active_fingerprint_uq
    ON recovery_action(source_task_id, cause, fingerprint)
    WHERE status IN ('active', 'escalated');

-- --- decomposition_claim: owner_run_id must reference a real run ---------------------------------

ALTER TABLE decomposition_claim RENAME TO decomposition_claim__old;
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
INSERT INTO decomposition_claim (id, source_task_id, accepted_plan_revision_id, status,
    request_fingerprint, requested_children, child_task_ids, owner_run_id, completed_at, created_at)
    SELECT id, source_task_id, accepted_plan_revision_id, status, request_fingerprint,
        requested_children, child_task_ids, owner_run_id, completed_at, created_at
        FROM decomposition_claim__old;
DROP TABLE decomposition_claim__old;
CREATE UNIQUE INDEX decomp_source_revision_uq
    ON decomposition_claim(source_task_id, accepted_plan_revision_id);
CREATE INDEX decomp_active_owner_idx ON decomposition_claim(owner_run_id)
    WHERE status = 'in_flight';
