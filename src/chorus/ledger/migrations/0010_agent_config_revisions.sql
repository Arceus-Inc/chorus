-- 0010_agent_config_revisions — immutable, reproducible effective harness configurations.
-- Immutable once applied: author a new migration instead of editing this one.

CREATE TABLE agent_config_revision (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id                  text NOT NULL CHECK (btrim(id) <> ''),
    agent_id            text NOT NULL CHECK (btrim(agent_id) <> ''),
    revision_no         integer NOT NULL CHECK (revision_no > 0),
    agents_md_revision  text NOT NULL CHECK (btrim(agents_md_revision) <> ''),
    agents_md_content   text NOT NULL,
    provider            text NOT NULL CHECK (btrim(provider) <> ''),
    model               text NOT NULL CHECK (btrim(model) <> ''),
    sandbox_profile     text NOT NULL CHECK (btrim(sandbox_profile) <> ''),
    created_at          timestamptz NOT NULL,
    PRIMARY KEY (company_id, id)
);

CREATE UNIQUE INDEX agent_config_revision_agent_number_uq
    ON agent_config_revision(company_id, agent_id, revision_no);

ALTER TABLE agent_config_revision ENABLE ROW LEVEL SECURITY;

ALTER TABLE agent_config_revision FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_config_revision_company_select ON agent_config_revision FOR SELECT
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE POLICY agent_config_revision_company_insert ON agent_config_revision FOR INSERT
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX agent_config_revision_agent_created_idx
    ON agent_config_revision(company_id, agent_id, created_at);

CREATE TABLE agent_config_revision_head (
    company_id        uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    agent_id          text NOT NULL CHECK (btrim(agent_id) <> ''),
    latest_revision_no integer NOT NULL CHECK (latest_revision_no > 0),
    PRIMARY KEY (company_id, agent_id)
);

ALTER TABLE agent_config_revision_head ENABLE ROW LEVEL SECURITY;

ALTER TABLE agent_config_revision_head FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_config_revision_head_company_select ON agent_config_revision_head FOR SELECT
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE POLICY agent_config_revision_head_company_insert ON agent_config_revision_head FOR INSERT
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE POLICY agent_config_revision_head_company_update ON agent_config_revision_head FOR UPDATE
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE TABLE agent_config_revision_skill (
    company_id               uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    agent_config_revision_id text NOT NULL,
    skill_revision_id        uuid NOT NULL,
    position                 integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (company_id, agent_config_revision_id, skill_revision_id),
    CONSTRAINT agent_config_revision_skill_config_fk
        FOREIGN KEY (company_id, agent_config_revision_id)
        REFERENCES agent_config_revision(company_id, id),
    CONSTRAINT agent_config_revision_skill_revision_fk
        FOREIGN KEY (company_id, skill_revision_id)
        REFERENCES skill_revision(company_id, id)
);

ALTER TABLE agent_config_revision_skill ENABLE ROW LEVEL SECURITY;

ALTER TABLE agent_config_revision_skill FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_config_revision_skill_company_select ON agent_config_revision_skill FOR SELECT
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE POLICY agent_config_revision_skill_company_insert ON agent_config_revision_skill FOR INSERT
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX agent_config_revision_skill_position_uq
    ON agent_config_revision_skill(company_id, agent_config_revision_id, position);

CREATE TABLE agent_config_revision_tool (
    company_id               uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    agent_config_revision_id text NOT NULL,
    identifier               text NOT NULL CHECK (btrim(identifier) <> ''),
    provenance               text NOT NULL CHECK (btrim(provenance) <> ''),
    position                 integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (company_id, agent_config_revision_id, identifier),
    CONSTRAINT agent_config_revision_tool_config_fk
        FOREIGN KEY (company_id, agent_config_revision_id)
        REFERENCES agent_config_revision(company_id, id)
);

ALTER TABLE agent_config_revision_tool ENABLE ROW LEVEL SECURITY;

ALTER TABLE agent_config_revision_tool FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_config_revision_tool_company_select ON agent_config_revision_tool FOR SELECT
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE POLICY agent_config_revision_tool_company_insert ON agent_config_revision_tool FOR INSERT
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE UNIQUE INDEX agent_config_revision_tool_position_uq
    ON agent_config_revision_tool(company_id, agent_config_revision_id, position);

ALTER TABLE eval_run
    DROP CONSTRAINT eval_run_agent_config_revision_check;

INSERT INTO agent_config_revision (
    company_id,
    id,
    agent_id,
    revision_no,
    agents_md_revision,
    agents_md_content,
    provider,
    model,
    sandbox_profile,
    created_at
)
SELECT
    company_id,
    agent_config_revision,
    'legacy-eval:' || agent_config_revision,
    1,
    'legacy-unpinned',
    '',
    'legacy-unpinned',
    'legacy-unpinned',
    'legacy-unpinned',
    min(created_at)
FROM eval_run
GROUP BY company_id, agent_config_revision;

INSERT INTO agent_config_revision_head (company_id, agent_id, latest_revision_no)
SELECT company_id, agent_id, max(revision_no)
FROM agent_config_revision
GROUP BY company_id, agent_id;

ALTER TABLE eval_run
    ADD CONSTRAINT eval_run_agent_config_revision_fk
    FOREIGN KEY (company_id, agent_config_revision)
    REFERENCES agent_config_revision(company_id, id);
