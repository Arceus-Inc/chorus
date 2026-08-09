-- 0009_rollouts — immutable rollout candidates and append-only promotion decisions.
-- Immutable once applied: author a new migration instead of editing this one.

CREATE UNIQUE INDEX eval_run_company_suite_revision_id_uq
    ON eval_run(company_id, id, eval_suite_id, skill_revision_id);

CREATE UNIQUE INDEX approval_company_id_uq ON approval(company_id, id);

CREATE TABLE rollout (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                uuid PRIMARY KEY,
    skill_revision_id uuid NOT NULL,
    eval_suite_id     uuid NOT NULL,
    eval_run_id       uuid NOT NULL,
    created_at        timestamptz NOT NULL,
    CONSTRAINT rollout_eval_run_pin_fk
        FOREIGN KEY (company_id, eval_run_id, eval_suite_id, skill_revision_id)
        REFERENCES eval_run(company_id, id, eval_suite_id, skill_revision_id)
);

CREATE UNIQUE INDEX rollout_company_id_uq ON rollout(company_id, id);

ALTER TABLE rollout ENABLE ROW LEVEL SECURITY;

ALTER TABLE rollout FORCE ROW LEVEL SECURITY;

CREATE POLICY rollout_company_isolation ON rollout
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX rollout_revision_created_idx ON rollout(company_id, skill_revision_id, created_at);

CREATE UNIQUE INDEX rollout_company_id_run_uq ON rollout(company_id, id, eval_run_id);

CREATE TABLE rollout_evidence (
    company_id           uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    rollout_id           uuid NOT NULL,
    eval_run_id          uuid NOT NULL,
    artifact_revision_id uuid NOT NULL,
    position             integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (company_id, rollout_id, artifact_revision_id),
    CONSTRAINT rollout_evidence_rollout_fk
        FOREIGN KEY (company_id, rollout_id, eval_run_id)
        REFERENCES rollout(company_id, id, eval_run_id) ON DELETE CASCADE,
    CONSTRAINT rollout_evidence_eval_run_artifact_fk
        FOREIGN KEY (company_id, eval_run_id, artifact_revision_id)
        REFERENCES eval_run_artifact_revision(company_id, eval_run_id, artifact_revision_id)
);

ALTER TABLE rollout_evidence ENABLE ROW LEVEL SECURITY;

ALTER TABLE rollout_evidence FORCE ROW LEVEL SECURITY;

CREATE POLICY rollout_evidence_company_isolation ON rollout_evidence
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX rollout_evidence_position_uq
    ON rollout_evidence(company_id, rollout_id, position);

CREATE TABLE rollout_decision (
    company_id          uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                  uuid PRIMARY KEY,
    rollout_id          uuid NOT NULL,
    stage               text NOT NULL CHECK (stage IN ('canary', 'full')),
    status              text NOT NULL CHECK (status IN ('completed', 'promoted')),
    approval_id         uuid,
    reviewer_user_id    text,
    replay_regression   text CHECK (replay_regression IN ('none', 'non_critical', 'critical')),
    created_at          timestamptz NOT NULL,
    CONSTRAINT rollout_decision_rollout_fk
        FOREIGN KEY (company_id, rollout_id) REFERENCES rollout(company_id, id) ON DELETE CASCADE,
    CONSTRAINT rollout_decision_approval_fk
        FOREIGN KEY (company_id, approval_id) REFERENCES approval(company_id, id),
    CONSTRAINT rollout_decision_stage_status_ck CHECK (
        (stage = 'canary' AND status = 'completed' AND approval_id IS NULL
            AND reviewer_user_id IS NULL AND replay_regression IS NULL)
        OR
        (stage = 'full' AND status = 'promoted' AND approval_id IS NOT NULL
            AND btrim(reviewer_user_id) <> '' AND replay_regression IN ('none', 'non_critical'))
    )
);

CREATE UNIQUE INDEX rollout_decision_company_id_uq ON rollout_decision(company_id, id);

ALTER TABLE rollout_decision ENABLE ROW LEVEL SECURITY;

ALTER TABLE rollout_decision FORCE ROW LEVEL SECURITY;

CREATE POLICY rollout_decision_company_isolation ON rollout_decision
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX rollout_decision_stage_uq ON rollout_decision(company_id, rollout_id, stage);
