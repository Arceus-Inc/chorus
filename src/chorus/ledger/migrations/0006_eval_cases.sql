-- 0006_eval_cases — reusable expectations pinned to one immutable skill revision.
-- Immutable once applied: author a new migration instead of editing this one.

CREATE UNIQUE INDEX skill_revision_company_id_uq
    ON skill_revision(company_id, id);

CREATE TABLE eval_case (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                uuid PRIMARY KEY,
    skill_revision_id uuid NOT NULL,
    name              text NOT NULL,
    input_text        text NOT NULL,
    expected_behavior text NOT NULL,
    created_at        timestamptz NOT NULL,
    CONSTRAINT eval_case_skill_revision_fk
        FOREIGN KEY (company_id, skill_revision_id)
        REFERENCES skill_revision(company_id, id) ON DELETE CASCADE
);

ALTER TABLE eval_case ENABLE ROW LEVEL SECURITY;

ALTER TABLE eval_case FORCE ROW LEVEL SECURITY;

CREATE POLICY eval_case_company_isolation ON eval_case
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX eval_case_revision_name_uq
    ON eval_case(company_id, skill_revision_id, name);

CREATE INDEX eval_case_revision_created_idx
    ON eval_case(company_id, skill_revision_id, created_at);
