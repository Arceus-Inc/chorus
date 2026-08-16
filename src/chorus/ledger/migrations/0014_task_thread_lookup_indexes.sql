-- 0014_task_thread_lookup_indexes — ordered task/run/cost lookups for the inspector projection.
-- Baseline schema stays frozen; these indexes ship as a delta only.
-- 0006_run_carryover already created run_task_created_idx on (task_id, created_at).
-- Rebuild it to include id so tied created_at rows match ORDER BY created_at, id.
DROP INDEX IF EXISTS run_task_created_idx;
CREATE INDEX run_task_created_idx ON run(task_id, created_at, id);

CREATE INDEX cost_event_run_occurred_idx ON cost_event(run_id, occurred_at, id);

-- Task-only spend is valid provenance too; run-linked rows use the index above.
CREATE INDEX cost_event_task_only_occurred_idx
    ON cost_event(task_id, occurred_at, id)
    WHERE run_id IS NULL;
