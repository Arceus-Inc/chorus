-- 0007_eval_suites — ordered eval cases pinned to one immutable skill revision.
-- Immutable once applied: author a new migration instead of editing this one.

CREATE UNIQUE INDEX eval_case_company_revision_id_uq
    ON eval_case(company_id, id, skill_revision_id);

CREATE TABLE eval_suite (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                uuid PRIMARY KEY,
    skill_revision_id uuid NOT NULL,
    created_at        timestamptz NOT NULL,
    CONSTRAINT eval_suite_skill_revision_fk
        FOREIGN KEY (company_id, skill_revision_id)
        REFERENCES skill_revision(company_id, id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX eval_suite_company_id_uq ON eval_suite(company_id, id);

CREATE UNIQUE INDEX eval_suite_company_revision_id_uq
    ON eval_suite(company_id, id, skill_revision_id);

ALTER TABLE eval_suite ENABLE ROW LEVEL SECURITY;

ALTER TABLE eval_suite FORCE ROW LEVEL SECURITY;

CREATE POLICY eval_suite_company_isolation ON eval_suite
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX eval_suite_revision_created_idx
    ON eval_suite(company_id, skill_revision_id, created_at);

CREATE TABLE eval_suite_case (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    suite_id          uuid NOT NULL,
    skill_revision_id uuid NOT NULL,
    case_id           uuid NOT NULL,
    position          integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (company_id, suite_id, case_id),
    CONSTRAINT eval_suite_case_suite_fk
        FOREIGN KEY (company_id, suite_id, skill_revision_id)
        REFERENCES eval_suite(company_id, id, skill_revision_id) ON DELETE CASCADE,
    CONSTRAINT eval_suite_case_case_fk
        FOREIGN KEY (company_id, case_id, skill_revision_id)
        REFERENCES eval_case(company_id, id, skill_revision_id)
);

ALTER TABLE eval_suite_case ENABLE ROW LEVEL SECURITY;

ALTER TABLE eval_suite_case FORCE ROW LEVEL SECURITY;

CREATE POLICY eval_suite_case_company_isolation ON eval_suite_case
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX eval_suite_case_position_uq
    ON eval_suite_case(company_id, suite_id, position);
