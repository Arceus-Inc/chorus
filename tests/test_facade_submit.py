"""The facade intake verb (spec 14 F2) — ``submit`` creates a depth-0 task, optionally wired.

The high-level front door: ``org.submit("build a login page", assignee="moe")`` creates the task and
hands it to its owner in one call. Optional ``dod`` / ``depends_on`` / ``priority`` wire the rest.
Fail-closed: an unknown assignee raises before anything is written.
"""

from __future__ import annotations

import pytest

from chorus.errors import UnknownEmployee
from chorus.facade import Caps, Chorus
from chorus.ledger import (
    ActivityVerb,
    DelegationContractStatus,
    ExecutionMode,
    Goal,
    ManagementProfile,
    OriginKind,
    SqliteLedger,
    TaskPriority,
    TaskStatus,
    TeamStatus,
)
from chorus.ledger._models import WakeReason
from chorus.observability import EventBus, LedgerInspector
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration


def _chorus(ledger: SqliteLedger) -> Chorus:
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=EventBus(),
        inspector=LedgerInspector(ledger),
        dream=None,
        roles=RoleRegistry.from_plugins(default_roles()),
        caps=Caps(),
    )


def test_submit_creates_a_backlog_depth0_task() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        task = _chorus(ledger).submit("build a login page")
        stored = ledger.tasks.get(task.id)
        assert stored is not None
        assert stored.intent == "build a login page"
        assert stored.depth == 0
        assert stored.status is TaskStatus.BACKLOG  # unassigned → parked in backlog
    finally:
        ledger.close()


def test_submit_with_assignee_assigns_and_wakes() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="moe", name="Moe", role="engineer"))
        task = _chorus(ledger).submit("build a login page", assignee="Moe")
        stored = ledger.tasks.get(task.id)
        assert stored is not None
        assert stored.assignee_employee_id == "moe"  # name resolved to slug
        assert stored.status is TaskStatus.TODO  # assignment moved it off backlog
        queued = ledger.wakes.queued(employee_id="moe")
        assert [w.reason for w in queued] == [WakeReason.TASK_ASSIGNED]
    finally:
        ledger.close()


def test_submit_unknown_assignee_is_fail_closed() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        with pytest.raises(UnknownEmployee):
            _chorus(ledger).submit("x", assignee="ghost")
        assert ledger.tasks.all() == []  # nothing written on the failed path
    finally:
        ledger.close()


def test_submit_with_dod_sets_it() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        task = _chorus(ledger).submit("ship", dod=Verifier.command("pytest -q"))
        assert ledger.dod.get_for_task(task.id) is not None
    finally:
        ledger.close()


def test_submit_with_depends_on_adds_edges() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger)
        prereq = chorus.submit("prereq")
        task = chorus.submit("the work", depends_on=(prereq.id,))
        assert ledger.dependencies.unresolved_blockers(task.id) == [prereq.id]
    finally:
        ledger.close()


def test_submit_honours_priority() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        task = _chorus(ledger).submit("urgent", priority=TaskPriority.HIGH)
        stored = ledger.tasks.get(task.id)
        assert stored is not None and stored.priority is TaskPriority.HIGH
    finally:
        ledger.close()


def _seed_delegation_lead(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="lead", name="Lead", role="engineer"))
    ledger.goals.create(Goal(id="goal-release", title="Release"))
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="lead",
            granted_by_user_id="user-admin",
            active=True,
            can_lead=True,
            can_subdelegate=True,
            max_delegation_depth=2,
            max_team_size=4,
            allowed_professions=("engineer",),
            spend_limit_cents=50_000,
            version=1,
        )
    )


def test_submit_root_delegation_atomically_wires_active_team_and_contract() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        _seed_delegation_lead(ledger)

        task = _chorus(ledger).submit(
            "coordinate the release",
            assignee="Lead",
            goal_id="goal-release",
            execution_mode=ExecutionMode.DELEGATION,
        )

        stored = ledger.tasks.get(task.id)
        assert stored is not None
        assert (stored.execution_mode, stored.assignee_employee_id, stored.status) == (
            ExecutionMode.DELEGATION,
            "lead",
            TaskStatus.TODO,
        )
        assert stored.team_id is not None
        team = ledger.teams.get(stored.team_id)
        assert team is not None
        assert (team.goal_id, team.lead_employee_id, team.status) == (
            "goal-release",
            "lead",
            TeamStatus.ACTIVE,
        )
        contract = ledger.delegation_contracts.get(task.id)
        assert contract is not None
        assert (
            contract.status,
            contract.management_profile_version,
            contract.can_subdelegate,
            contract.max_depth,
            contract.max_team_size,
            contract.spend_limit_cents,
            contract.objective_rubric,
        ) == (
            DelegationContractStatus.DELEGATED,
            1,
            True,
            2,
            4,
            50_000,
            "coordinate the release",
        )
        assert [wake.reason for wake in ledger.wakes.queued(employee_id="lead")] == [
            WakeReason.TASK_ASSIGNED
        ]
        contract_events = ledger.activity.by_subject("delegation_contract", task.id)
        assert [event.verb for event in contract_events] == [ActivityVerb.DELEGATION_CREATED]
        assert contract_events[0].payload == {"root": True, "team_id": stored.team_id}
    finally:
        ledger.close()


def test_horizon_root_delegation_fingerprint_is_exact_once_at_facade_boundary() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        _seed_delegation_lead(ledger)
        chorus = _chorus(ledger)

        first = chorus.submit(
            "coordinate the release",
            assignee="Lead",
            goal_id="goal-release",
            origin_kind=OriginKind.HORIZON_INTAKE,
            origin_fingerprint="goal-release:v1",
            execution_mode=ExecutionMode.DELEGATION,
        )
        retry = chorus.submit(
            "coordinate the release",
            assignee="Lead",
            goal_id="goal-release",
            origin_kind=OriginKind.HORIZON_INTAKE,
            origin_fingerprint="goal-release:v1",
            execution_mode=ExecutionMode.DELEGATION,
        )

        assert retry.id == first.id
        assert len(ledger.tasks.all()) == 1
        assert len(ledger.teams.list_active()) == 1
        assert len(ledger.delegation_contracts.list()) == 1
        assert len(ledger.wakes.queued(employee_id="lead")) == 1
        assert len(ledger.activity.by_subject("delegation_contract", first.id)) == 1
    finally:
        ledger.close()


def test_submit_root_delegation_rolls_back_the_whole_kickoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        _seed_delegation_lead(ledger)

        def fail_contract_create(contract: object) -> None:
            raise RuntimeError("injected contract persistence failure")

        monkeypatch.setattr(ledger.delegation_contracts, "create", fail_contract_create)

        with pytest.raises(RuntimeError, match="injected contract persistence failure"):
            _chorus(ledger).submit(
                "coordinate the release",
                assignee="Lead",
                goal_id="goal-release",
                execution_mode=ExecutionMode.DELEGATION,
            )

        assert ledger.tasks.all() == []
        assert ledger.teams.for_goal("goal-release") is None
        assert ledger.wakes.queued(employee_id="lead") == []
        assert ledger.activity.all() == []

        monkeypatch.undo()
        task = _chorus(ledger).submit(
            "coordinate the release",
            assignee="Lead",
            goal_id="goal-release",
            execution_mode=ExecutionMode.DELEGATION,
        )

        team = ledger.teams.for_goal("goal-release")
        assert team is not None
        assert len(ledger.tasks.all()) == 1
        assert ledger.delegation_contracts.get(task.id) is not None
        assert [member.employee_id for member in ledger.team_members.members_of(team.id)] == [
            "lead"
        ]
        assert [
            event.verb for event in ledger.activity.by_subject("team", team.id)
        ] == [ActivityVerb.TEAM_FORMED, ActivityVerb.TEAM_ACTIVATED]
    finally:
        ledger.close()
