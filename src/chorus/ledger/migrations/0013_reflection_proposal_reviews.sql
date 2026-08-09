-- 0013_reflection_proposal_reviews — one append-only human verdict per exact proposal revision.
-- Immutable once applied: author a new migration instead of editing this one.

CREATE TABLE reflection_proposal_review (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id uuid NOT NULL,
    proposal_artifact_revision_id uuid NOT NULL,
    verdict text NOT NULL CHECK (verdict IN ('accepted', 'rejected')),
    reviewer_user_id text NOT NULL CHECK (btrim(reviewer_user_id) <> ''),
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (company_id, id),
    UNIQUE (company_id, proposal_artifact_revision_id),
    CONSTRAINT reflection_proposal_review_proposal_fk
        FOREIGN KEY (company_id, proposal_artifact_revision_id)
        REFERENCES reflection_proposal(company_id, artifact_revision_id)
);

ALTER TABLE reflection_proposal_review ENABLE ROW LEVEL SECURITY;

ALTER TABLE reflection_proposal_review FORCE ROW LEVEL SECURITY;

CREATE POLICY reflection_proposal_review_company_select
    ON reflection_proposal_review FOR SELECT
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE POLICY reflection_proposal_review_company_insert
    ON reflection_proposal_review FOR INSERT
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));
