"""plan_approval — sign off a manager's decomposed plan (§5 governance, Approach A), end to end.

A manager decomposes; with the plan gate on, the children are held ``blocked`` and a ``plan_approval``
gate opens on the parent. Approve releases the children to ``todo`` + wakes them; deny cancels them and
strands the parent with a recovery card; revise cancels them and re-wakes the manager to re-plan.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.governance import ApprovalDecision, GovernanceResolver
from chorus.ledger import (
    ApprovalAction,
    DelegationContract,
    DelegationContractStatus,
    ExecutionMode,
    Goal,
    ManagementProfile,
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

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
_USER = "lead"


def _decomposed_and_gated(ledger: SqliteLedger) -> str:
    """A manager (moe) decomposes G into two children, then a plan gate is opened. Returns gate id."""
    ledger.employees.create(Employee(id="moe", name="moe", role="backend_engineer"))
    for emp in ("ada", "bob"):
        ledger.employees.create(
            Employee(id=emp, name=emp, role="backend_engineer", reports_to="moe")
        )
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="moe",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            max_delegation_depth=1,
            max_team_size=3,
            allowed_professions=("backend_engineer",),
            version=1,
        )
    )
    ledger.goals.create(Goal(id="goal-G", title="Ship"))
    ledger.teams.create(
        Team(
            id="team-G",
            name="Delivery Team",
            lead_employee_id="moe",
            created_by="operator",
            status=TeamStatus.ACTIVE,
        )
    )
    ledger.team_members.add(
        TeamMember(
            team_id="team-G",
            employee_id="moe",
            source_manager_id="moe",
            membership_role=TeamMembershipRole.LEAD,
        )
    )
    ledger.tasks.submit(
        Task(
            id="G",
            intent="ship",
            status=TaskStatus.TODO,
            execution_mode=ExecutionMode.DELEGATION,
            team_id="team-G",
            goal_id="goal-G",
            assignee_employee_id="moe",
        )
    )
    ledger.delegation_contracts.create(
        DelegationContract(
            task_id="G",
            team_id="team-G",
            lead_employee_id="moe",
            management_profile_version=1,
            max_depth=1,
            max_team_size=3,
            objective_rubric="the approved plan is integrated",
            status=DelegationContractStatus.DELEGATED,
        )
    )
    CapabilityService(ledger).decompose(
        parent_id="G",
        revision="r1",
        children=[
            ChildPlan(label="api", intent="build the api", assignee="ada"),
            ChildPlan(label="ui", intent="build the ui", assignee="bob"),
        ],
        actor_employee_id="moe",
    )
    approval = GovernanceResolver(ledger).open_plan_gate("G", reason="sign off the plan")
    return approval.id


def test_open_holds_the_children_blocked(ledger: SqliteLedger) -> None:
    _decomposed_and_gated(ledger)
    statuses = {c.origin_fingerprint: c.status for c in ledger.tasks.children("G")}
    assert statuses == {"api": TaskStatus.BLOCKED, "ui": TaskStatus.BLOCKED}
    # the children's assignment wakes were dropped — neither engineer is dispatchable yet
    queued = {w.employee_id for w in ledger.wakes.queued()}
    assert "ada" not in queued and "bob" not in queued


def test_approve_releases_children_to_todo_and_wakes_them(ledger: SqliteLedger) -> None:
    gate = _decomposed_and_gated(ledger)

    outcome = GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
    )

    statuses = {c.origin_fingerprint: c.status for c in ledger.tasks.children("G")}
    assert statuses == {"api": TaskStatus.TODO, "ui": TaskStatus.TODO}
    assert outcome.wakes_fired == 2  # exactly the two released children
    assert {"ada", "bob"} <= {w.employee_id for w in ledger.wakes.queued()}


def test_deny_cancels_children_and_strands_the_parent(ledger: SqliteLedger) -> None:
    gate = _decomposed_and_gated(ledger)

    GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.DENY, decided_by_user_id=_USER, now=_NOW
    )

    statuses = {c.origin_fingerprint: c.status for c in ledger.tasks.children("G")}
    assert statuses == {"api": TaskStatus.CANCELLED, "ui": TaskStatus.CANCELLED}
    assert ledger.tasks.get("G").status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert ledger.recovery_actions.active_for_source("G") is not None


def test_revise_cancels_children_and_rewakes_the_manager(ledger: SqliteLedger) -> None:
    gate = _decomposed_and_gated(ledger)

    outcome = GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.REQUEST_REVISION, decided_by_user_id=_USER, now=_NOW
    )

    assert ledger.tasks.get("G").status is TaskStatus.TODO  # type: ignore[union-attr]
    assert outcome.wakes_fired == 1
    assert {w.employee_id for w in ledger.wakes.queued()} == {"moe"}  # the manager re-plans


def test_handler_action_kind(ledger: SqliteLedger) -> None:
    from chorus.governance._actions import PlanApprovalAction

    assert PlanApprovalAction.action is ApprovalAction.PLAN_APPROVAL
