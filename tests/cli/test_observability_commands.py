"""CLI observability surfaces for org and manager scrum packet rollups."""

from __future__ import annotations

import io

from chorus.ledger import (
    DelegationContract,
    DelegationContractStatus,
    ExecutionMode,
    Goal,
    ManagementProfile,
    Run,
    RunStatus,
    SqliteLedger,
    Task,
    TaskStatus,
    Team,
    TeamMember,
    TeamMembershipRole,
    TeamStatus,
)
from chorus.lifecycle import CapabilityService, ChildPlan
from chorus.workforce import Employee
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    signal = dispatch(
        line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY
    )
    return signal, buffer.getvalue()


def _seed(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="mgr", name="Moe", role="backend_engineer"))
    ledger.employees.create(
        Employee(id="ada", name="Ada", role="backend_engineer", reports_to="mgr")
    )
    ledger.employees.create(
        Employee(id="bob", name="Bob", role="backend_engineer", reports_to="mgr")
    )
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="mgr",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            max_delegation_depth=1,
            max_team_size=3,
            allowed_professions=("backend_engineer",),
            version=1,
        )
    )
    ledger.goals.create(Goal(id="goal-M", title="Ship"))
    ledger.teams.create(
        Team(
            id="team-M",
            name="Feature Team",
            lead_employee_id="mgr",
            created_by="operator",
            status=TeamStatus.ACTIVE,
        )
    )
    ledger.team_members.add(
        TeamMember(
            team_id="team-M",
            employee_id="mgr",
            source_manager_id="mgr",
            membership_role=TeamMembershipRole.LEAD,
        )
    )
    ledger.tasks.submit(
        Task(
            id="M",
            intent="ship",
            status=TaskStatus.TODO,
            assignee_employee_id="mgr",
            execution_mode=ExecutionMode.DELEGATION,
            team_id="team-M",
            goal_id="goal-M",
        )
    )
    ledger.delegation_contracts.create(
        DelegationContract(
            task_id="M",
            team_id="team-M",
            lead_employee_id="mgr",
            management_profile_version=1,
            max_depth=1,
            max_team_size=3,
            objective_rubric="the complete feature is integrated",
            status=DelegationContractStatus.DELEGATED,
        )
    )
    ledger.runs.create(
        Run(id="run_mgr_1", employee_id="mgr", task_id="M", status=RunStatus.RUNNING)
    )
    CapabilityService(ledger).decompose(
        parent_id="M",
        revision="run_mgr_1",
        children=(
            ChildPlan(label="api", intent="build api", assignee="ada"),
            ChildPlan(label="ui", intent="build ui", assignee="bob", depends_on=("api",)),
        ),
        actor_employee_id="mgr",
    )


def test_check_org_reports_combined_manager_and_leaf_metrics(ledger: SqliteLedger) -> None:
    _seed(ledger)

    _, out = _run("check org", CliSession(ledger=ledger))

    assert "employees" in out
    assert "managers" in out
    assert "leaves" in out
    assert "decomposition_count" in out
    assert "manager" in out and "completion" in out


def test_check_scrum_reports_one_manager_packet(ledger: SqliteLedger) -> None:
    _seed(ledger)

    _, out = _run("check scrum M", CliSession(ledger=ledger))

    assert "parent_task" in out
    assert "completion_rate" in out
    assert "reassignments" in out
    assert "api" in out and "ui" in out
