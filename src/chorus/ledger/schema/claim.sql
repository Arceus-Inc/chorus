-- claim — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE claim (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id          uuid PRIMARY KEY,
    decision_id uuid NOT NULL,
    text        text NOT NULL,
    source_url  text NOT NULL,
    confidence  double precision NOT NULL,
    created_at  timestamptz NOT NULL
);

ALTER TABLE claim ENABLE ROW LEVEL SECURITY;

ALTER TABLE claim FORCE ROW LEVEL SECURITY;

CREATE POLICY claim_company_isolation ON claim USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX claim_decision ON claim(decision_id);
