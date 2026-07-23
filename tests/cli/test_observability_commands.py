"""CLI observability surfaces for org and manager scrum packet rollups."""

from __future__ import annotations

import io

from chorus.ledger import (
    DelegationContract,
    DelegationContractStatus,
    ExecutionMode,
    Goal,
    Ledger,
    ManagementProfile,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    Team,
    TeamMember,
    TeamMembershipRole,
    TeamStatus,
)
from chorus.lifecycle import CapabilityService, ChildPlan
from chorus.testing import uid
from chorus.workforce import Employee
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    signal = dispatch(
        line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY
    )
    return signal, buffer.getvalue()


def _seed(ledger: Ledger) -> None:
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
    ledger.goals.create(Goal(id=uid("goal-M"), title="Ship"))
    ledger.teams.create(
        Team(
            id=uid("team-M"),
            name="Feature Team",
            lead_employee_id="mgr",
            created_by="operator",
            status=TeamStatus.ACTIVE,
        )
    )
    ledger.team_members.add(
        TeamMember(
            team_id=uid("team-M"),
            employee_id="mgr",
            source_manager_id="mgr",
            membership_role=TeamMembershipRole.LEAD,
        )
    )
    ledger.tasks.submit(
        Task(
            id=uid("M"),
            intent="ship",
            status=TaskStatus.TODO,
            assignee_employee_id="mgr",
            execution_mode=ExecutionMode.DELEGATION,
            team_id=uid("team-M"),
            goal_id=uid("goal-M"),
        )
    )
    ledger.delegation_contracts.create(
        DelegationContract(
            task_id=uid("M"),
            team_id=uid("team-M"),
            lead_employee_id="mgr",
            management_profile_version=1,
            max_depth=1,
            max_team_size=3,
            objective_rubric="the complete feature is integrated",
            status=DelegationContractStatus.DELEGATED,
        )
    )
    ledger.runs.create(
        Run(id=uid("run_mgr_1"), employee_id="mgr", task_id=uid("M"), status=RunStatus.RUNNING)
    )
    CapabilityService(ledger).decompose(
        parent_id=uid("M"),
        revision=uid("run_mgr_1"),
        children=(
            ChildPlan(label="api", intent="build api", assignee="ada"),
            ChildPlan(label="ui", intent="build ui", assignee="bob", depends_on=("api",)),
        ),
        actor_employee_id="mgr",
    )


def test_check_org_reports_combined_manager_and_leaf_metrics(ledger: Ledger) -> None:
    _seed(ledger)

    _, out = _run("check org", CliSession(ledger=ledger))

    assert "employees" in out
    assert "managers" in out
    assert "leaves" in out
    assert "decomposition_count" in out
    assert "manager" in out and "completion" in out


def test_check_scrum_reports_one_manager_packet(ledger: Ledger) -> None:
    _seed(ledger)

    _, out = _run(f"check scrum {uid('M')}", CliSession(ledger=ledger))

    assert "parent_task" in out
    assert "completion_rate" in out
    assert "reassignments" in out
    assert "api" in out and "ui" in out
