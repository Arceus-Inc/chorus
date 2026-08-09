-- 0008_eval_runs — append-only, reproducible records for revision-pinned evaluation executions.
-- Immutable once applied: author a new migration instead of editing this one.

CREATE UNIQUE INDEX artifact_revision_company_id_uq ON artifact_revision(company_id, id);

CREATE TABLE eval_run (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                    uuid PRIMARY KEY,
    eval_suite_id         uuid NOT NULL,
    skill_revision_id     uuid NOT NULL,
    agent_config_revision text NOT NULL CHECK (btrim(agent_config_revision) <> ''),
    provider              text NOT NULL CHECK (btrim(provider) <> ''),
    model                 text NOT NULL CHECK (btrim(model) <> ''),
    input_snapshot        text NOT NULL,
    output_snapshot       text NOT NULL,
    input_tokens          bigint NOT NULL CHECK (input_tokens >= 0),
    output_tokens         bigint NOT NULL CHECK (output_tokens >= 0),
    cost_usd              numeric NOT NULL CHECK (cost_usd >= 0),
    status                text NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    started_at            timestamptz,
    completed_at          timestamptz,
    created_at            timestamptz NOT NULL,
    CONSTRAINT eval_run_suite_revision_fk
        FOREIGN KEY (company_id, eval_suite_id, skill_revision_id)
        REFERENCES eval_suite(company_id, id, skill_revision_id),
    CONSTRAINT eval_run_timestamp_order_ck
        CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);

CREATE UNIQUE INDEX eval_run_company_id_uq ON eval_run(company_id, id);

ALTER TABLE eval_run ENABLE ROW LEVEL SECURITY;

ALTER TABLE eval_run FORCE ROW LEVEL SECURITY;

CREATE POLICY eval_run_company_isolation ON eval_run
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX eval_run_suite_created_idx ON eval_run(company_id, eval_suite_id, created_at);

CREATE TABLE eval_run_artifact_revision (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    eval_run_id          uuid NOT NULL,
    artifact_revision_id uuid NOT NULL,
    position             integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (company_id, eval_run_id, artifact_revision_id),
    CONSTRAINT eval_run_artifact_revision_run_fk
        FOREIGN KEY (company_id, eval_run_id)
        REFERENCES eval_run(company_id, id) ON DELETE CASCADE,
    CONSTRAINT eval_run_artifact_revision_artifact_fk
        FOREIGN KEY (company_id, artifact_revision_id)
        REFERENCES artifact_revision(company_id, id)
);

ALTER TABLE eval_run_artifact_revision ENABLE ROW LEVEL SECURITY;

ALTER TABLE eval_run_artifact_revision FORCE ROW LEVEL SECURITY;

CREATE POLICY eval_run_artifact_revision_company_isolation ON eval_run_artifact_revision
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX eval_run_artifact_revision_position_uq
    ON eval_run_artifact_revision(company_id, eval_run_id, position);
