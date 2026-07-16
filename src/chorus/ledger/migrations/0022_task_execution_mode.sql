-- Migration 0022 — explicit task execution contract (M8 §5.5).

ALTER TABLE task ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'delivery';
ALTER TABLE task ADD COLUMN team_id TEXT;