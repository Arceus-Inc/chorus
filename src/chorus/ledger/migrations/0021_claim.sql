-- Migration 0021 — claim (the claims ledger, pm design doc §10).
-- One cited fact a decision rests on: text + its source_url citation + a confidence. This is what
-- makes a recommendation checkable (faithfulness) — "this decision rests on THESE sources".
-- Immutable once shipped: never edit; add a new numbered .sql instead.

CREATE TABLE claim (
    id          TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    text        TEXT NOT NULL,
    source_url  TEXT NOT NULL,
    confidence  REAL NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX claim_decision ON claim(decision_id);
