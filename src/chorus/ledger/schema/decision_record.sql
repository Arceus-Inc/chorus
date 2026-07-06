-- decision_record — an immutable, ADR-style product decision (pm design doc §10).
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
