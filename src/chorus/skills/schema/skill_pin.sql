-- skill_pin: optional per-employee pin to a historical revision (NULL revision_id = live HEAD).
CREATE TABLE skill_pin (
    employee_id   TEXT NOT NULL,
    slug          TEXT NOT NULL,
    revision_id   TEXT REFERENCES skill_revision(id) ON DELETE SET NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (employee_id, slug)
);
