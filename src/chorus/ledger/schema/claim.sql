-- claim — one cited fact a decision rests on (the claims ledger, pm design doc §10).
CREATE TABLE claim (
    id          TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    text        TEXT NOT NULL,
    source_url  TEXT NOT NULL,
    confidence  REAL NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX claim_decision ON claim(decision_id);
