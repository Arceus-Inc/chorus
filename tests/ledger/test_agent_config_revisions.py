"""Immutable agent configuration snapshots for reproducible harness inputs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from chorus.ledger import (
    AgentConfigRevision,
    AgentIdentity,
    AgentsMdReference,
    EffectiveToolPin,
    Ledger,
    LedgerIntegrityError,
    ProviderModelConfig,
    SandboxProfile,
    Skill,
    SkillOrigin,
    SkillRevision,
    SkillRevisionPin,
)
from chorus.testing import uid


def _skill_revision(ledger: Ledger, suffix: str) -> SkillRevision:
    skill = ledger.skills.insert(
        Skill(
            id=uid(f"agent-config-skill-{suffix}"),
            employee_id="agent-config-employee",
            slug=f"agent-config-skill-{suffix}",
            name="Agent config skill",
            origin=SkillOrigin.CREATED,
        )
    )
    return ledger.skill_revisions.append(
        SkillRevision(
            id=uid(f"agent-config-skill-revision-{suffix}"),
            skill_id=skill.id,
            revision_no=1,
            action="create",
            file_inventory="[]",
            content_hash=suffix,
        )
    )


def _revision(
    ledger: Ledger,
    suffix: str,
    *,
    revision_no: int = 1,
    skill_pins: tuple[SkillRevisionPin, ...] = (),
    tool_pins: tuple[EffectiveToolPin, ...] = (),
) -> AgentConfigRevision:
    return AgentConfigRevision(
        id=uid(f"agent-config-revision-{suffix}"),
        agent=AgentIdentity(f"agent-{suffix}"),
        revision_no=revision_no,
        agents_md=AgentsMdReference(revision="agents-md@3", content="# Agent instructions\n"),
        provider_model=ProviderModelConfig(provider="anthropic", model="claude-sonnet"),
        sandbox_profile=SandboxProfile("workspace-write"),
        skill_pins=skill_pins,
        tool_pins=tool_pins,
    )


def test_agent_config_revision_round_trips_ordered_pins_and_tool_provenance(
    ledger: Ledger,
) -> None:
    first = _skill_revision(ledger, "first")
    second = _skill_revision(ledger, "second")
    revision = _revision(
        ledger,
        "one",
        skill_pins=(SkillRevisionPin(second.id), SkillRevisionPin(first.id)),
        tool_pins=(
            EffectiveToolPin("shell", "builtin"),
            EffectiveToolPin("search", "plugin:exa"),
        ),
    )

    created = ledger.agent_config_revisions.create(revision)

    assert created.created_at is not None
    assert created.skill_pins == (SkillRevisionPin(second.id), SkillRevisionPin(first.id))
    assert created.tool_pins == (
        EffectiveToolPin("shell", "builtin"),
        EffectiveToolPin("search", "plugin:exa"),
    )
    assert ledger.agent_config_revisions.get(created.id) == created
    assert ledger.agent_config_revisions.list(revision.agent) == [created]


def test_agent_config_revision_ids_are_provider_neutral_text(ledger: Ledger) -> None:
    revision = AgentConfigRevision(
        id="agent-config@42",
        agent=AgentIdentity("agent-text-id"),
        revision_no=1,
        agents_md=AgentsMdReference("agents-md@1", "instructions"),
        provider_model=ProviderModelConfig("anthropic", "claude-sonnet"),
        sandbox_profile=SandboxProfile("workspace-write"),
    )

    assert ledger.agent_config_revisions.create(revision).id == "agent-config@42"


def test_agent_config_revision_rejects_invalid_pins_and_identity_fields() -> None:
    with pytest.raises(ValueError, match="agent config revision number must be positive"):
        AgentConfigRevision(
            id=uid("invalid-agent-config"),
            agent=AgentIdentity("agent"),
            revision_no=0,
            agents_md=AgentsMdReference("agents-md@1", "instructions"),
            provider_model=ProviderModelConfig("provider", "model"),
            sandbox_profile=SandboxProfile("workspace-write"),
        )

    with pytest.raises(ValueError, match="agent identity must not be blank"):
        AgentIdentity("  ")

    with pytest.raises(ValueError, match=r"AGENTS\.md revision must not be blank"):
        AgentsMdReference("  ", "instructions")

    with pytest.raises(ValueError, match="sandbox profile must not be blank"):
        SandboxProfile("  ")

    with pytest.raises(ValueError, match="skill revision pin must not be blank"):
        SkillRevisionPin("  ")

    with pytest.raises(ValueError, match="effective tool identifier must not be blank"):
        EffectiveToolPin("  ", "builtin")

    with pytest.raises(ValueError, match="effective tool provenance must not be blank"):
        EffectiveToolPin("tool", "  ")

    with pytest.raises(ValueError, match="skill pins must not contain duplicates"):
        AgentConfigRevision(
            id=uid("duplicate-skills"),
            agent=AgentIdentity("agent"),
            revision_no=1,
            agents_md=AgentsMdReference("agents-md@1", "instructions"),
            provider_model=ProviderModelConfig("provider", "model"),
            sandbox_profile=SandboxProfile("workspace-write"),
            skill_pins=(
                SkillRevisionPin(uid("skill-revision")),
                SkillRevisionPin(uid("skill-revision")),
            ),
        )

    with pytest.raises(ValueError, match="effective tool pins must not contain duplicates"):
        AgentConfigRevision(
            id=uid("duplicate-tools"),
            agent=AgentIdentity("agent"),
            revision_no=1,
            agents_md=AgentsMdReference("agents-md@1", "instructions"),
            provider_model=ProviderModelConfig("provider", "model"),
            sandbox_profile=SandboxProfile("workspace-write"),
            tool_pins=(
                EffectiveToolPin("tool", "builtin"),
                EffectiveToolPin("tool", "plugin:override"),
            ),
        )


def test_agent_config_revision_requires_local_skill_pins_and_unique_agent_revision(
    pg_database: str,
) -> None:
    company_a = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    company_b = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        foreign_skill = _skill_revision(company_a, "foreign")
        with pytest.raises(LedgerIntegrityError):
            company_b.agent_config_revisions.create(
                _revision(
                    company_b,
                    "foreign-skill",
                    skill_pins=(SkillRevisionPin(foreign_skill.id),),
                )
            )

        company_b.agent_config_revisions.create(_revision(company_b, "same-agent", revision_no=2))
        with pytest.raises(ValueError, match="agent config revision number must increase"):
            company_b.agent_config_revisions.create(
                AgentConfigRevision(
                    id=uid("agent-config-revision-same-agent-second"),
                    agent=AgentIdentity("agent-same-agent"),
                    revision_no=1,
                    agents_md=AgentsMdReference("agents-md@4", "new instructions"),
                    provider_model=ProviderModelConfig("anthropic", "claude-sonnet"),
                    sandbox_profile=SandboxProfile("workspace-write"),
                )
            )

        shared_id = "agent-config@shared"
        company_a.agent_config_revisions.create(
            AgentConfigRevision(
                id=shared_id,
                agent=AgentIdentity("shared-agent"),
                revision_no=1,
                agents_md=AgentsMdReference("agents-md@1", "instructions"),
                provider_model=ProviderModelConfig("anthropic", "claude-sonnet"),
                sandbox_profile=SandboxProfile("workspace-write"),
            )
        )
        company_b.agent_config_revisions.create(
            AgentConfigRevision(
                id=shared_id,
                agent=AgentIdentity("shared-agent"),
                revision_no=1,
                agents_md=AgentsMdReference("agents-md@1", "instructions"),
                provider_model=ProviderModelConfig("anthropic", "claude-sonnet"),
                sandbox_profile=SandboxProfile("workspace-write"),
            )
        )
    finally:
        company_a.close()
        company_b.close()


def test_agent_config_revisions_are_append_only_for_the_runtime_role(pg_database: str) -> None:
    import psycopg

    company_id = str(uuid.uuid4())
    ledger = Ledger.open(pg_database, company_id=company_id)
    try:
        revision = ledger.agent_config_revisions.create(_revision(ledger, "append-only"))
    finally:
        ledger.close()

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'chorus_config_app') "
            "THEN CREATE ROLE chorus_config_app LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO chorus_config_app")
        admin.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON agent_config_revision, "
            "agent_config_revision_skill, agent_config_revision_tool TO chorus_config_app"
        )

    app_conninfo = pg_database.replace("user=postgres", "user=chorus_config_app")
    with psycopg.connect(app_conninfo, autocommit=True) as app:
        app.execute("SELECT set_config('app.company_id', %s, false)", (company_id,))
        updated = app.execute(
            "UPDATE agent_config_revision SET model = 'rewritten' WHERE id = %s RETURNING id",
            (revision.id,),
        ).fetchall()
        deleted = app.execute(
            "DELETE FROM agent_config_revision WHERE id = %s RETURNING id", (revision.id,)
        ).fetchall()
        persisted = app.execute(
            "SELECT model FROM agent_config_revision WHERE id = %s", (revision.id,)
        ).fetchone()

    assert updated == []
    assert deleted == []
    assert persisted == ("claude-sonnet",)


def test_database_serializes_agent_revision_publication(pg_database: str) -> None:
    import psycopg

    company_id = str(uuid.uuid4())
    advance = (
        "INSERT INTO agent_config_revision_head "
        "(company_id, agent_id, latest_revision_no) VALUES (%s, 'agent-concurrent', %s) "
        "ON CONFLICT (company_id, agent_id) DO UPDATE "
        "SET latest_revision_no = EXCLUDED.latest_revision_no "
        "WHERE agent_config_revision_head.latest_revision_no < EXCLUDED.latest_revision_no "
        "RETURNING latest_revision_no"
    )
    with (
        psycopg.connect(pg_database) as later_revision,
        psycopg.connect(pg_database) as earlier_revision,
    ):
        assert later_revision.execute(advance, (company_id, 3)).fetchone() == (3,)
        earlier_revision.execute("SET lock_timeout = '100ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            earlier_revision.execute(advance, (company_id, 2))
        earlier_revision.rollback()
        later_revision.commit()

        assert earlier_revision.execute(advance, (company_id, 2)).fetchone() is None


def test_migration_backfills_legacy_eval_config_references(pg_database: str) -> None:
    import psycopg

    company_id = str(uuid.uuid4())
    eval_run_id = str(uuid.uuid4())
    now = datetime(2026, 8, 9, tzinfo=UTC)
    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute(
            "ALTER TABLE eval_run DROP CONSTRAINT eval_run_agent_config_revision_fk"
        )
        admin.execute(
            "ALTER TABLE eval_run ADD CONSTRAINT eval_run_agent_config_revision_check "
            "CHECK (btrim(agent_config_revision) <> '')"
        )
        admin.execute("DROP TABLE agent_config_revision_skill")
        admin.execute("DROP TABLE agent_config_revision_tool")
        admin.execute("DROP TABLE agent_config_revision_head")
        admin.execute("DROP TABLE agent_config_revision")
        admin.execute(
            "DELETE FROM chorus_schema_migrations WHERE id = '0010_agent_config_revisions'"
        )
        admin.execute("SET session_replication_role = replica")
        admin.execute(
            "INSERT INTO eval_run (company_id, id, eval_suite_id, skill_revision_id, "
            "agent_config_revision, provider, model, input_snapshot, output_snapshot, "
            "input_tokens, output_tokens, cost_usd, status, started_at, completed_at, created_at) "
            "VALUES (%s, %s, %s, %s, 'agent-config@42', 'anthropic', 'claude-sonnet', "
            "'input', 'output', 1, 1, 0, 'completed', %s, %s, %s)",
            (company_id, eval_run_id, str(uuid.uuid4()), str(uuid.uuid4()), now, now, now),
        )
        admin.execute("SET session_replication_role = origin")

    migrated = Ledger.open(pg_database, company_id=company_id)
    try:
        legacy = migrated.agent_config_revisions.get("agent-config@42")
        assert legacy is not None
        assert legacy.provider_model == ProviderModelConfig(
            "legacy-unpinned", "legacy-unpinned"
        )
        assert legacy.agents_md.revision == "legacy-unpinned"
    finally:
        migrated.close()
