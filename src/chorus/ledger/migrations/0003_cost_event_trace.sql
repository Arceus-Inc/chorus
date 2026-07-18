-- 0003_cost_event_trace — cost_event.trace_id: the lineage-root task id, stamped at record time
-- so spend joins the same trace as the run's events (OBS §3/§5: one correlation spine; the
-- product maps the root to its run). Nullable: rows recorded before this delta have no trace.
-- Immutable once applied: author a new migration instead of editing this one.

ALTER TABLE cost_event ADD COLUMN trace_id uuid;

CREATE INDEX cost_event_trace_idx ON cost_event(company_id, trace_id);
