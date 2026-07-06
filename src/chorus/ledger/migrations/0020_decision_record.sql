-- Migration 0020 — decision_record (pm design doc §10, the Decision OS).
-- An immutable, ADR-style product decision: the bet, its confidence, the rejected alternatives, the
-- outcome metric, and a revisit trigger. A change never edits a row — it supersedes with a new id
-- (superseded_by points forward). rejected_alternatives is a JSON array of {option, reason}.
-- Immutable once shipped: never edit; add a new numbered .sql instead.

CREATE TABLE decision_record (
    id                    TEXT PRIMARY KEY,
    task_id               TEXT NOT NULL,
    option                TEXT NOT NULL,
    rationale             TEXT NOT NULL,
    confidence            REAL NOT NULL,
    outcome_metric        TEXT NOT NULL,
    revisit_trigger       TEXT NOT NULL,
    rejected_alternatives TEXT NOT NULL DEFAULT '[]',
    superseded_by         TEXT,
    created_at            TEXT NOT NULL
);

CREATE INDEX decision_record_task ON decision_record(task_id);
