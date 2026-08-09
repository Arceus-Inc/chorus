-- 0014_reflection_application_authorizations — accepted proposal to separate-run handoff.
-- Immutable once applied: author a new migration instead of editing this one.

CREATE UNIQUE INDEX reflection_proposal_company_revision_source_uq
    ON reflection_proposal(company_id, artifact_revision_id, source_run_id);

CREATE UNIQUE INDEX reflection_proposal_review_company_id_proposal_uq
    ON reflection_proposal_review(company_id, id, proposal_artifact_revision_id);

CREATE TABLE reflection_application_authorization (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id uuid NOT NULL,
    proposal_artifact_revision_id uuid NOT NULL,
    review_id uuid NOT NULL,
    proposal_source_run_id uuid NOT NULL,
    application_run_id uuid NOT NULL,
    authorized_by_user_id text NOT NULL CHECK (btrim(authorized_by_user_id) <> ''),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (company_id, id),
    UNIQUE (company_id, proposal_artifact_revision_id),
    UNIQUE (company_id, application_run_id),
    CONSTRAINT reflection_application_proposal_fk
        FOREIGN KEY (company_id, proposal_artifact_revision_id, proposal_source_run_id)
        REFERENCES reflection_proposal(company_id, artifact_revision_id, source_run_id),
    CONSTRAINT reflection_application_review_fk
        FOREIGN KEY (company_id, review_id, proposal_artifact_revision_id)
        REFERENCES reflection_proposal_review(company_id, id, proposal_artifact_revision_id),
    CONSTRAINT reflection_application_run_fk
        FOREIGN KEY (company_id, application_run_id)
        REFERENCES run(company_id, id),
    CONSTRAINT reflection_application_separate_run
        CHECK (proposal_source_run_id <> application_run_id)
);

ALTER TABLE reflection_application_authorization ENABLE ROW LEVEL SECURITY;

ALTER TABLE reflection_application_authorization FORCE ROW LEVEL SECURITY;

CREATE POLICY reflection_application_authorization_company_select
    ON reflection_application_authorization FOR SELECT
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE POLICY reflection_application_authorization_company_insert
    ON reflection_application_authorization FOR INSERT
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));
