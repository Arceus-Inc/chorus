-- 0011_run_config_pins — execution runs retain the immutable harness config they used.
-- Immutable once applied: author a new migration instead of editing this one.

ALTER TABLE run
    ADD COLUMN agent_config_revision text;

ALTER TABLE run
    ADD CONSTRAINT run_agent_config_revision_fk
    FOREIGN KEY (company_id, agent_config_revision)
    REFERENCES agent_config_revision(company_id, id);
