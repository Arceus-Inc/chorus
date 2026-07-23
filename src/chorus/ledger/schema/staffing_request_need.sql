-- staffing_request_need — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE staffing_request_need (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    request_id                  uuid NOT NULL REFERENCES staffing_request(id),
    profession                  text NOT NULL,
    count                       integer NOT NULL,
    PRIMARY KEY (request_id, profession)
);

ALTER TABLE staffing_request_need ENABLE ROW LEVEL SECURITY;

ALTER TABLE staffing_request_need FORCE ROW LEVEL SECURITY;

CREATE POLICY staffing_request_need_company_isolation ON staffing_request_need USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));
