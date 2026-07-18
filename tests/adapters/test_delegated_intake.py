"""Dream delegated-intake contract adapted to Chorus root delegation."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from dream.contracts.delegation import (
    DelegatedIntakePort,
    DelegatedWorkRef,
    DelegatedWorkRequest,
    StaffingBlocked,
    StaffingRequirement,
)

from chorus.adapters import DelegatedIntakeAdapter
from chorus.facade import Caps, Chorus
from chorus.ledger import (
    DelegationContractStatus,
    ExecutionMode,
    Goal,
    Ledger,
    ManagementProfile,
    OriginKind,
    TaskPriority,
    TeamStatus,
)
from chorus.observability import EventBus, LedgerInspector
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import open_test_ledger, uid
from chorus.workforce import Employee
from chorus.workforce._ledger import LedgerWorkforce


@pytest.fixture
def ledger() -> Iterator[Ledger]:
    store = open_test_ledger()
    try:
        yield store
    finally:
        store.close()


def _chorus(ledger: Ledger) -> Chorus:
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=EventBus(),
        inspector=LedgerInspector(ledger),
        dream=None,
        roles=RoleRegistry.from_plugins(default_roles()),
        caps=Caps(request_depth_cap=3),
    )


def _lead(ledger: Ledger, employee_id: str = "lead") -> Employee:
    ledger.employees.create(Employee(id=employee_id, name=employee_id.title(), role="engineer"))
    ledger.employees.create(
        Employee(
            id=f"{employee_id}-report",
            name=f"{employee_id.title()} Report",
            role="engineer",
            reports_to=employee_id,
        )
    )
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id=employee_id,
            granted_by_user_id="user-admin",
            active=True,
            can_lead=True,
            can_subdelegate=True,
            max_delegation_depth=5,
            max_team_size=5,
            allowed_professions=("engineer",),
            spend_limit_cents=50_000,
            version=1,
        )
    )
    persisted = ledger.employees.get(employee_id)
    assert persisted is not None
    return persisted


def _request(*, fingerprint: str = "goal-8:v1") -> DelegatedWorkRequest:
    return DelegatedWorkRequest(
        intent="Ship M8",
        goal_id=uid("goal-8"),
        priority="high",
        requirements=(StaffingRequirement("engineer"),),
        max_team_size=3,
        spend_limit_cents=20_000,
        origin_fingerprint=fingerprint,
    )


def test_adapter_conforms_and_creates_root_delegation(ledger: Ledger) -> None:
    lead = _lead(ledger)
    ledger.goals.create(Goal(id=uid("goal-8"), title="Ship M8"))
    adapter = DelegatedIntakeAdapter(_chorus(ledger), ledger, company_id="company")

    result = adapter.submit_delegated(_request())

    assert isinstance(adapter, DelegatedIntakePort)
    assert isinstance(result, DelegatedWorkRef)
    assert result.lead_id == lead.id
    task = ledger.tasks.get(result.root_task_id)
    assert task is not None
    assert task.execution_mode is ExecutionMode.DELEGATION
    assert task.priority is TaskPriority.HIGH
    assert task.origin_kind is OriginKind.HORIZON_INTAKE
    assert task.origin_fingerprint == "goal-8:v1"
    assert task.team_id == result.team_id
    assert task.assignee_employee_id == lead.id
    team = ledger.teams.get(result.team_id)
    assert team is not None
    assert team.status is TeamStatus.ACTIVE
    contract = ledger.delegation_contracts.get(task.id)
    assert contract is not None
    assert contract.status is DelegationContractStatus.DELEGATED
    assert contract.max_depth == 3
    assert contract.max_team_size == 3
    assert contract.spend_limit_cents == 20_000


def test_same_origin_fingerprint_returns_same_durable_ref(ledger: Ledger) -> None:
    _lead(ledger)
    ledger.goals.create(Goal(id=uid("goal-8"), title="Ship M8"))
    adapter = DelegatedIntakeAdapter(_chorus(ledger), ledger, company_id="company")

    first = adapter.submit_delegated(_request())
    second = adapter.submit_delegated(_request())

    assert isinstance(first, DelegatedWorkRef)
    assert second == first
    assert len(ledger.tasks.all()) == 1
    assert len(ledger.teams.list_active()) == 1
    assert ledger.delegation_contracts.get(first.root_task_id) is not None


def test_no_eligible_lead_returns_blocked_without_mutation(ledger: Ledger) -> None:
    ledger.goals.create(Goal(id=uid("goal-8"), title="Ship M8"))
    adapter = DelegatedIntakeAdapter(_chorus(ledger), ledger, company_id="company")

    result = adapter.submit_delegated(_request())

    assert isinstance(result, StaffingBlocked)
    assert result.goal_id == uid("goal-8")
    assert ledger.tasks.all() == []
    assert ledger.teams.list_active() == []
    assert ledger.wakes.queued() == []


def test_retry_returns_original_lead_before_reselecting(ledger: Ledger) -> None:
    original = _lead(ledger, "zulu")
    ledger.goals.create(Goal(id=uid("goal-8"), title="Ship M8"))
    adapter = DelegatedIntakeAdapter(_chorus(ledger), ledger, company_id="company")
    first = adapter.submit_delegated(_request())
    assert isinstance(first, DelegatedWorkRef)
    assert first.lead_id == original.id
    _lead(ledger, "alpha")

    retry = adapter.submit_delegated(_request())

    assert retry == first


def test_concurrent_retry_is_exact_once_across_connections_and_restart() -> None:
    seed = open_test_ledger(company_id=uid("delegated-intake-restart"))
    dsn = seed._conn._pg.info.dsn  # every "connection" below reopens this same database
    _lead(seed)
    seed.goals.create(Goal(id=uid("goal-8"), title="Ship M8"))
    seed.close()

    barrier = Barrier(2)

    def submit_from_connection(_: int) -> DelegatedWorkRef | StaffingBlocked:
        store = Ledger.open(dsn, company_id=uid("delegated-intake-restart"))
        adapter = DelegatedIntakeAdapter(_chorus(store), store, company_id="company")
        original = store.tasks.find_by_origin
        call_count = 0

        def synchronized_find(*args: object, _original=original) -> object:
            nonlocal call_count
            call_count += 1
            result = _original(*args)
            if call_count <= 2:
                barrier.wait()
            return result

        store.tasks.find_by_origin = synchronized_find  # type: ignore[method-assign]
        try:
            return adapter.submit_delegated(_request())
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        refs = list(executor.map(submit_from_connection, range(2)))

    assert isinstance(refs[0], DelegatedWorkRef)
    assert refs == [refs[0], refs[0]]

    reopened = Ledger.open(dsn, company_id=uid("delegated-intake-restart"))
    try:
        assert len(reopened.tasks.all()) == 1
        assert len(reopened.teams.list()) == 1
        assert len(reopened.delegation_contracts.list()) == 1
        assert len(reopened.team_members.members_of(refs[0].team_id)) == 1
        assert len(reopened.wakes.queued(employee_id=refs[0].lead_id)) == 1
        assert len(reopened.activity.by_subject("delegation_contract", refs[0].root_task_id)) == 1
    finally:
        reopened.close()
