-- 0012_reflection_proposals — immutable, proposal-only Reflection Coach artifacts.
-- Immutable once applied: author a new migration instead of editing this one.

CREATE UNIQUE INDEX artifact_company_id_uq ON artifact(company_id, id);

CREATE UNIQUE INDEX artifact_revision_company_id_artifact_id_uq
    ON artifact_revision(company_id, id, artifact_id);

CREATE UNIQUE INDEX run_company_id_uq ON run(company_id, id);

CREATE UNIQUE INDEX run_company_id_id_task_id_uq ON run(company_id, id, task_id);

CREATE UNIQUE INDEX routine_run_company_id_uq ON routine_run(company_id, id);

CREATE TABLE reflection_proposal (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    artifact_id uuid NOT NULL,
    artifact_revision_id uuid NOT NULL,
    target_kind text NOT NULL CHECK (target_kind IN ('agents_md', 'skill', 'tool_description')),
    target_owner_employee_id text NOT NULL CHECK (btrim(target_owner_employee_id) <> ''),
    target_id text NOT NULL CHECK (btrim(target_id) <> ''),
    target_revision text NOT NULL CHECK (btrim(target_revision) <> ''),
    diff text NOT NULL CHECK (btrim(diff) <> ''),
    rationale text NOT NULL CHECK (btrim(rationale) <> ''),
    source_routine_run_id uuid NOT NULL,
    source_run_id uuid NOT NULL,
    source_employee_id text NOT NULL CHECK (btrim(source_employee_id) <> ''),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (company_id, artifact_revision_id),
    UNIQUE (company_id, artifact_id),
    CONSTRAINT reflection_proposal_artifact_fk
        FOREIGN KEY (company_id, artifact_id)
        REFERENCES artifact(company_id, id),
    CONSTRAINT reflection_proposal_revision_fk
        FOREIGN KEY (company_id, artifact_revision_id, artifact_id)
        REFERENCES artifact_revision(company_id, id, artifact_id),
    CONSTRAINT reflection_proposal_routine_run_fk
        FOREIGN KEY (company_id, source_routine_run_id)
        REFERENCES routine_run(company_id, id),
    CONSTRAINT reflection_proposal_run_fk
        FOREIGN KEY (company_id, source_run_id)
        REFERENCES run(company_id, id),
    CONSTRAINT reflection_proposal_employee_fk
        FOREIGN KEY (company_id, source_employee_id)
        REFERENCES employee(company_id, id),
    CONSTRAINT reflection_proposal_target_owner_fk
        FOREIGN KEY (company_id, target_owner_employee_id)
        REFERENCES employee(company_id, id),
    CONSTRAINT reflection_proposal_no_self_target
        CHECK (source_employee_id <> target_owner_employee_id)
);

ALTER TABLE reflection_proposal ENABLE ROW LEVEL SECURITY;

ALTER TABLE reflection_proposal FORCE ROW LEVEL SECURITY;

CREATE POLICY reflection_proposal_company_select ON reflection_proposal FOR SELECT
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE POLICY reflection_proposal_company_insert ON reflection_proposal FOR INSERT
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX reflection_proposal_target_idx
    ON reflection_proposal(
        company_id,
        target_kind,
        target_owner_employee_id,
        target_id,
        target_revision,
        created_at
    );

CREATE TABLE reflection_proposal_evidence (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    proposal_artifact_revision_id uuid NOT NULL,
    evidence_artifact_revision_id uuid NOT NULL,
    position integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (company_id, proposal_artifact_revision_id, evidence_artifact_revision_id),
    CONSTRAINT reflection_proposal_evidence_proposal_fk
        FOREIGN KEY (company_id, proposal_artifact_revision_id)
        REFERENCES reflection_proposal(company_id, artifact_revision_id),
    CONSTRAINT reflection_proposal_evidence_artifact_fk
        FOREIGN KEY (company_id, evidence_artifact_revision_id)
        REFERENCES artifact_revision(company_id, id)
);

ALTER TABLE reflection_proposal_evidence ENABLE ROW LEVEL SECURITY;

ALTER TABLE reflection_proposal_evidence FORCE ROW LEVEL SECURITY;

CREATE POLICY reflection_proposal_evidence_company_select ON reflection_proposal_evidence FOR SELECT
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE POLICY reflection_proposal_evidence_company_insert ON reflection_proposal_evidence FOR INSERT
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX reflection_proposal_evidence_position_uq
    ON reflection_proposal_evidence(company_id, proposal_artifact_revision_id, position);

CREATE TABLE reflection_proposal_trajectory (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    proposal_artifact_revision_id uuid NOT NULL,
    trajectory_run_id uuid NOT NULL,
    trajectory_task_id uuid NOT NULL,
    position integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (company_id, proposal_artifact_revision_id, trajectory_run_id),
    CONSTRAINT reflection_proposal_trajectory_proposal_fk
        FOREIGN KEY (company_id, proposal_artifact_revision_id)
        REFERENCES reflection_proposal(company_id, artifact_revision_id),
    CONSTRAINT reflection_proposal_trajectory_run_fk
        FOREIGN KEY (company_id, trajectory_run_id, trajectory_task_id)
        REFERENCES run(company_id, id, task_id)
);

ALTER TABLE reflection_proposal_trajectory ENABLE ROW LEVEL SECURITY;

ALTER TABLE reflection_proposal_trajectory FORCE ROW LEVEL SECURITY;

CREATE POLICY reflection_proposal_trajectory_company_select
    ON reflection_proposal_trajectory FOR SELECT
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE POLICY reflection_proposal_trajectory_company_insert
    ON reflection_proposal_trajectory FOR INSERT
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX reflection_proposal_trajectory_position_uq
    ON reflection_proposal_trajectory(company_id, proposal_artifact_revision_id, position);
