ALTER TABLE task
    ADD COLUMN IF NOT EXISTS files_to_touch text[] NOT NULL DEFAULT ARRAY[]::text[];
