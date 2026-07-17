-- episodic_record — Postgres-native (uuid/timestamptz/jsonb; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.
-- Append-only per-beat episodic capture (spec 07 §3-§6). search_text is the Python-normalized
-- intent + narrative(body) prose the repo writes at append; the GIN tsvector index over it
-- replaces the retired SQLite FTS5 record_fts table (BM25 → ts_rank, snippet → ts_headline).

CREATE TABLE episodic_record (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    run_id      uuid PRIMARY KEY,
    task_id     uuid NOT NULL,
    employee_id text NOT NULL,
    scope       text NOT NULL DEFAULT 'project',
    role        text NOT NULL DEFAULT '',
    intent      text NOT NULL DEFAULT '',
    outcome     text NOT NULL DEFAULT '',
    score       double precision NOT NULL DEFAULT 0,
    body        text NOT NULL DEFAULT '',
    artifacts   jsonb NOT NULL DEFAULT '[]'::jsonb,
    files_touched jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at  timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    pin_count   integer NOT NULL DEFAULT 0,
    last_recalled_at timestamptz,
    tier        text NOT NULL DEFAULT 'hot',
    search_text text NOT NULL DEFAULT ''
);

ALTER TABLE episodic_record ENABLE ROW LEVEL SECURITY;

ALTER TABLE episodic_record FORCE ROW LEVEL SECURITY;

CREATE POLICY episodic_record_company_isolation ON episodic_record USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX episodic_record_employee_idx ON episodic_record(company_id, employee_id, recorded_at);

CREATE INDEX episodic_record_recall_idx ON episodic_record(company_id, employee_id, tier, recorded_at DESC);

CREATE INDEX episodic_record_fts_idx ON episodic_record USING gin (to_tsvector('simple', search_text));
