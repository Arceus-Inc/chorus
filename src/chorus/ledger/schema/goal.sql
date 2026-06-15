-- Cluster D: goal (the alignment tree). Declarative; applied via migrations/.
CREATE TABLE goal (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    level             TEXT NOT NULL DEFAULT 'company',
    status            TEXT NOT NULL DEFAULT 'active',
    parent_id         TEXT REFERENCES goal(id),
    owner_employee_id TEXT REFERENCES employee(id),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
