-- Migration 0006 — activity (spec 01 Cluster G): the append-only audit stream.
-- Immutable once shipped: never edit; add a new numbered .sql instead.
-- Declarative copy lives in ../schema/activity.sql; test_schema_parity asserts they agree.
-- No FK on actor: a governance log must survive the actor being removed (e.g. a fired employee).

CREATE TABLE activity (
    id                 TEXT PRIMARY KEY,
    actor_employee_id  TEXT,
    actor_user_id      TEXT,
    verb               TEXT NOT NULL,
    subject_kind       TEXT NOT NULL,
    subject_id         TEXT NOT NULL,
    trace_id           TEXT,
    payload            TEXT NOT NULL DEFAULT '{}',
    occurred_at        TEXT NOT NULL,
    CONSTRAINT activity_single_actor CHECK (actor_employee_id IS NULL OR actor_user_id IS NULL)
);

CREATE INDEX activity_subject_idx ON activity(subject_kind, subject_id);
CREATE INDEX activity_occurred_idx ON activity(occurred_at);
