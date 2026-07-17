-- task — Postgres-native (uuid/timestamptz/jsonb/boolean; company_id + FORCE RLS).
-- Loaded by chorus.ledger.baseline(); tables are FK-dependency-ordered at load.

CREATE TABLE task (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                     uuid PRIMARY KEY,
    parent_id              uuid REFERENCES task(id),
    goal_id                uuid REFERENCES goal(id),
    intent                 text NOT NULL,
    status                 text NOT NULL DEFAULT 'backlog',
    priority               text NOT NULL DEFAULT 'medium',
    assignee_employee_id   text,
    assignee_user_id       text,
    checkout_run_id        uuid,
    execution_run_id       uuid,
    depth                  integer NOT NULL DEFAULT 0,
    request_depth          integer NOT NULL DEFAULT 0,
    origin_kind            text NOT NULL DEFAULT 'manual',
    origin_id              text,
    origin_fingerprint     text NOT NULL DEFAULT 'default',
    created_by_employee_id text,
    created_by_user_id     text,
    created_at             timestamptz NOT NULL,
    updated_at             timestamptz NOT NULL,
    started_at             timestamptz,
    completed_at           timestamptz,
    cancelled_at           timestamptz,
    trust_preset           text,
    trust_boundary         jsonb,
    execution_mode         text NOT NULL DEFAULT 'delivery',
    team_id                text,
    CONSTRAINT task_single_assignee
        CHECK (assignee_employee_id IS NULL OR assignee_user_id IS NULL),
    FOREIGN KEY (company_id, assignee_employee_id) REFERENCES employee (company_id, id)
);

ALTER TABLE task ENABLE ROW LEVEL SECURITY;

ALTER TABLE task FORCE ROW LEVEL SECURITY;

CREATE POLICY task_company_isolation ON task USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX task_assignee_status_idx ON task(assignee_employee_id, status);

CREATE INDEX task_parent_idx ON task(parent_id);

CREATE INDEX task_goal_idx ON task(goal_id);

CREATE INDEX task_status_idx ON task(status);

CREATE INDEX task_origin_idx ON task(origin_kind, origin_id);

CREATE UNIQUE INDEX task_horizon_intake_fingerprint_uq
    ON task (company_id, origin_kind, origin_fingerprint)
    WHERE origin_kind = 'horizon_intake';

CREATE UNIQUE INDEX task_open_routine_uq
    ON task(origin_kind, origin_id, origin_fingerprint)
    WHERE origin_kind = 'routine_execution' AND origin_id IS NOT NULL
          AND execution_run_id IS NOT NULL
          AND status IN ('backlog','todo','in_progress','in_review','blocked');

CREATE UNIQUE INDEX task_active_stranded_recovery_uq
    ON task(origin_kind, origin_id)
    WHERE origin_kind = 'stranded_recovery' AND origin_id IS NOT NULL
          AND status NOT IN ('done','cancelled');

CREATE UNIQUE INDEX task_active_stale_run_eval_uq
    ON task(origin_kind, origin_id)
    WHERE origin_kind = 'stale_run_eval' AND origin_id IS NOT NULL
          AND status NOT IN ('done','cancelled');

CREATE UNIQUE INDEX task_active_productivity_review_uq
    ON task(origin_kind, origin_id)
    WHERE origin_kind = 'productivity_review' AND origin_id IS NOT NULL
          AND status NOT IN ('done','cancelled');
