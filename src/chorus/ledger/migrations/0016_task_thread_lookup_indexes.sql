-- Task-thread provenance performs ordered lookups by task/run. Keep those reads indexed.
CREATE INDEX run_task_created_idx ON run(task_id, created_at, id);

CREATE INDEX cost_event_run_occurred_idx ON cost_event(run_id, occurred_at, id);

-- Task-only spend is valid provenance too; run-linked rows use the index above.
CREATE INDEX cost_event_task_only_occurred_idx
    ON cost_event(task_id, occurred_at, id)
    WHERE run_id IS NULL;
