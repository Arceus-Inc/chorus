-- 0004_workforce_plan_origin_task — workforce_plan.proposed_in_task_id: the beat task the CEO
-- proposed this plan under. A proposal task is done when its proposal is decided (free-run,
-- found live 2026-07-18: an applied plan's formation task re-beat forever) — approve completes
-- the origin task through this link. Nullable: plans proposed outside a beat have no origin.
-- Immutable once applied: author a new migration instead of editing this one.

ALTER TABLE workforce_plan ADD COLUMN proposed_in_task_id uuid;
