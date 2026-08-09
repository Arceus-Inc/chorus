-- 0006_lattice_selection_seal_outbox — durable cross-component Lattice seal commands.
-- Immutable once applied: author a new migration instead of editing this one.

ALTER TABLE run
    ADD CONSTRAINT run_company_id_id_uq UNIQUE (company_id, id);

CREATE TABLE lattice_selection_seal_outbox (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    beat_run_id uuid NOT NULL,
    employee_id text NOT NULL,
    outcome_phase text NOT NULL CHECK (outcome_phase IN (
        'cancelled',
        'delegated',
        'terminal_pass',
        'terminal_fail',
        'needs_rework',
        'stranded'
    )),
    landed_at timestamptz NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at timestamptz,
    last_error text,
    sealed_at timestamptz,
    terminal_at timestamptz,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (company_id, beat_run_id),
    FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id),
    FOREIGN KEY (company_id, beat_run_id) REFERENCES run (company_id, id),
    CHECK (NOT (sealed_at IS NOT NULL AND terminal_at IS NOT NULL)),
    CHECK (
        (sealed_at IS NULL AND terminal_at IS NULL AND next_attempt_at IS NOT NULL)
        OR (sealed_at IS NOT NULL AND terminal_at IS NULL AND next_attempt_at IS NULL)
        OR (sealed_at IS NULL AND terminal_at IS NOT NULL AND next_attempt_at IS NULL)
    )
);

ALTER TABLE lattice_selection_seal_outbox ENABLE ROW LEVEL SECURITY;

ALTER TABLE lattice_selection_seal_outbox FORCE ROW LEVEL SECURITY;

CREATE POLICY lattice_selection_seal_outbox_company_isolation
    ON lattice_selection_seal_outbox
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX lattice_selection_seal_outbox_due_idx
    ON lattice_selection_seal_outbox (company_id, next_attempt_at, beat_run_id)
    WHERE sealed_at IS NULL AND terminal_at IS NULL;
