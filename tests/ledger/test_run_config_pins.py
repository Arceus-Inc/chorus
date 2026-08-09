"""Execution runs pin the immutable agent configuration used to perform them."""

from __future__ import annotations

import uuid

import pytest

from chorus.ledger import (
    AgentConfigRevision,
    AgentConfigRevisionRef,
    AgentIdentity,
    AgentsMdReference,
    Ledger,
    LedgerIntegrityError,
    ProviderModelConfig,
    Run,
    SandboxProfile,
    Task,
)
from chorus.testing import uid
from chorus.workforce import Employee


def _config(ledger: Ledger, *, config_id: str, agent_id: str) -> AgentConfigRevision:
    return ledger.agent_config_revisions.create(
        AgentConfigRevision(
            id=config_id,
            agent=AgentIdentity(agent_id),
            revision_no=1,
            agents_md=AgentsMdReference("agents-md@1", "instructions"),
            provider_model=ProviderModelConfig("anthropic", "claude-sonnet"),
            sandbox_profile=SandboxProfile("workspace-write"),
        )
    )


def _run(ledger: Ledger, *, config_id: str | None = None) -> Run:
    employee = ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    task = ledger.tasks.submit(Task(id=uid("run-config-task"), intent="ship it"))
    return Run(
        id=uid("run-config-run"),
        employee_id=employee.id,
        task_id=task.id,
        agent_config_revision=(AgentConfigRevisionRef(config_id) if config_id is not None else None),
    )


def test_execution_run_round_trips_an_optional_agent_config_revision(ledger: Ledger) -> None:
    unpinned = ledger.runs.create(_run(ledger))
    assert unpinned.agent_config_revision is None
    persisted_unpinned = ledger.runs.get(unpinned.id)
    assert persisted_unpinned is not None
    assert persisted_unpinned.agent_config_revision is None

    config = _config(ledger, config_id="agent-config@run-1", agent_id="ada")
    created = ledger.runs.create(
        Run(
            id=uid("run-config-pinned-run"),
            employee_id="ada",
            task_id=uid("run-config-task"),
            agent_config_revision=AgentConfigRevisionRef(config.id),
        )
    )

    assert created.agent_config_revision == AgentConfigRevisionRef(config.id)
    persisted = ledger.runs.get(created.id)
    assert persisted is not None
    assert persisted.agent_config_revision == AgentConfigRevisionRef(config.id)

    unrelated = _config(ledger, config_id="agent-config@other", agent_id="bex")
    with pytest.raises(ValueError, match="must belong to the run principal"):
        ledger.runs.create(
            Run(
                id=uid("run-config-wrong-agent"),
                employee_id="ada",
                task_id=uid("run-config-task"),
                agent_config_revision=AgentConfigRevisionRef(unrelated.id),
            )
        )


def test_execution_run_rejects_a_cross_tenant_agent_config_revision(pg_database: str) -> None:
    company_a = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    company_b = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        foreign_config = _config(company_a, config_id="agent-config@foreign", agent_id="ada")
        run = _run(company_b, config_id=foreign_config.id)

        with pytest.raises(LedgerIntegrityError):
            company_b.runs.create(run)
    finally:
        company_b.close()
        company_a.close()


def test_migration_leaves_historical_execution_runs_unpinned(pg_database: str) -> None:
    import psycopg

    company_id = str(uuid.uuid4())
    employee_id = "legacy-employee"
    task_id = uid("legacy-run-task")
    run_id = uid("legacy-run")
    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute("ALTER TABLE run DROP CONSTRAINT run_agent_config_revision_fk")
        admin.execute("ALTER TABLE run DROP COLUMN agent_config_revision")
        admin.execute("DELETE FROM chorus_schema_migrations WHERE id = '0011_run_config_pins'")
        admin.execute("SET session_replication_role = replica")
        admin.execute(
            "INSERT INTO employee (company_id, id, name, role, status, created_at, updated_at) "
            "VALUES (%s, %s, 'Legacy', 'engineer', 'active', now(), now())",
            (company_id, employee_id),
        )
        admin.execute(
            "INSERT INTO task (company_id, id, intent, status, created_at, updated_at) "
            "VALUES (%s, %s, 'legacy task', 'todo', now(), now())",
            (company_id, task_id),
        )
        admin.execute(
            "INSERT INTO run (company_id, id, employee_id, task_id, status, outcome, usage, "
            "created_at, principal_kind) "
            "VALUES (%s, %s, %s, %s, 'queued', '{}', '{}', now(), 'employee')",
            (company_id, run_id, employee_id, task_id),
        )
        admin.execute("SET session_replication_role = origin")

    migrated = Ledger.open(pg_database, company_id=company_id)
    try:
        run = migrated.runs.get(run_id)
        assert run is not None
        assert run.agent_config_revision is None
    finally:
        migrated.close()
