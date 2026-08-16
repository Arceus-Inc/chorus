"""Pending acceptance owns a delegated parent; cap CAS must not write DoD first."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from tests.heartbeat.test_scheduler_execution_profile import (
    _NOW,
    _authorization,
    _RecordingBeat,
    _RecordingMemory,
    _seed_delegation,
    _SubtreeLander,
)

from chorus.governance import ApprovalDecision, GovernanceError, GovernanceResolver
from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.heartbeat._execution_profile import ExecutionProfileResolver
from chorus.ledger import (
    ApprovalGate,
    ApprovalStatus,
    DelegationContractStatus,
    DodStatus,
    Ledger,
    Run,
    RunStatus,
    TaskStatus,
    TeamStatus,
    WakeStatus,
)
from chorus.outcomes import LanderRegistry, Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import LedgerWorkforce

pytestmark = pytest.mark.integration


def _open_pair(pg_database: str) -> tuple[Ledger, Ledger]:
    company_id = str(uuid.uuid4())
    return (
        Ledger.open(pg_database, company_id=company_id),
        Ledger.open(pg_database, company_id=company_id),
    )


def _human_approval_scheduler(ledger: Ledger, *, max_integrate_iterations: int = 3) -> Scheduler:
    return Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=_RecordingBeat(),
        roles=RoleRegistry.from_plugins(default_roles()),
        memory_writer=_RecordingMemory(),
        landers=LanderRegistry.from_landers([_SubtreeLander()]),
        max_concurrent_runs=1,
        max_integrate_iterations=max_integrate_iterations,
    )


async def _open_acceptance_gate(ledger: Ledger) -> None:
    _seed_delegation(ledger)
    ledger.dod.create(uid("task-release"), Verifier.human_approval())
    scheduler = _human_approval_scheduler(ledger)
    await scheduler.tick(_NOW)
    await scheduler.drain()


async def test_lost_cap_finish_cas_leaves_dod_and_integration_untouched(pg_database: str) -> None:
    ledger, racer = _open_pair(pg_database)
    try:
        lead = _seed_delegation(ledger)
        task = ledger.tasks.get(uid("task-release"))
        assert task is not None
        roles = RoleRegistry.from_plugins(default_roles())
        profile = ExecutionProfileResolver(roles, ledger).resolve(lead, task)
        run_id = uid("cap-run")
        ledger.runs.create(
            Run(
                id=run_id,
                employee_id=lead.id,
                task_id=task.id,
                wake_id=uid("wake-release"),
                status=RunStatus.RUNNING,
                started_at=datetime(2026, 6, 17, 12, tzinfo=UTC),
            )
        )
        assert racer.runs.finish(run_id, RunStatus.CANCELLED) is True
        wake = ledger.wakes.get(uid("wake-release"))
        assert wake is not None
        scheduler = Scheduler(
            ledger=ledger,
            roles=roles,
            max_integrate_iterations=0,
        )

        handled = await scheduler._maybe_cap_integrate(
            ledger,
            wake=wake,
            run_id=run_id,
            task=task,
            employee=lead,
            now=_NOW,
            execution_profile=profile,
        )

        assert handled is True
        assert ledger.dod.get_for_task(task.id) is None
        assert racer.dod.get_for_task(task.id) is None
        contract = ledger.delegation_contracts.get(task.id)
        assert contract is not None and contract.status is DelegationContractStatus.INTEGRATING
        assert contract.accepted_run_id is None
        assert ledger.tasks.get(task.id).status is TaskStatus.TODO  # type: ignore[union-attr]
        assert ledger.recovery_actions.active_for_source(task.id) is None
        kept = ledger.runs.get(run_id)
        assert kept is not None and kept.status is RunStatus.CANCELLED
        leftover = ledger.wakes.get(uid("wake-release"))
        assert leftover is not None and leftover.status is WakeStatus.QUEUED
    finally:
        ledger.close()
        racer.close()


async def test_leftover_children_done_keeps_verifying_so_authenticated_approve_lands(
    ledger: Ledger,
) -> None:
    await _open_acceptance_gate(ledger)
    pending = ledger.approvals.pending()
    assert len(pending) == 1 and pending[0].gate_kind is ApprovalGate.ACCEPTANCE
    contract = ledger.delegation_contracts.get(uid("task-release"))
    assert contract is not None and contract.status is DelegationContractStatus.VERIFYING
    accepted_run_id = contract.accepted_run_id
    dod = ledger.dod.get_for_task(uid("task-release"))
    assert dod is not None and dod.integration_ok is True
    assert ledger.tasks.get(uid("task-release")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]

    leftover_id = uid("leftover-children-done")
    ledger.wakes.enqueue(
        Wake(
            id=leftover_id,
            employee_id="lead",
            reason=WakeReason.CHILDREN_DONE,
            payload={"task_id": uid("task-release")},
        )
    )
    scheduler = _human_approval_scheduler(ledger)
    await scheduler.tick(_NOW)
    await scheduler.drain()

    kept = ledger.delegation_contracts.get(uid("task-release"))
    assert kept is not None and kept.status is DelegationContractStatus.VERIFYING
    assert kept.accepted_run_id == accepted_run_id
    after = ledger.dod.get_for_task(uid("task-release"))
    assert after is not None and after.integration_ok is True and after.status is DodStatus.PENDING
    assert ledger.tasks.get(uid("task-release")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert ledger.recovery_actions.active_for_source(uid("task-release")) is None
    still_pending = ledger.approvals.pending()
    assert len(still_pending) == 1 and still_pending[0].id == pending[0].id
    leftover = ledger.wakes.get(leftover_id)
    assert leftover is not None and leftover.status is WakeStatus.DONE

    GovernanceResolver(ledger).resolve_authenticated(
        pending[0].id,
        decision=ApprovalDecision.APPROVE,
        authorization=_authorization("leftover-wake"),
    )
    assert ledger.tasks.get(uid("task-release")).status is TaskStatus.DONE  # type: ignore[union-attr]
    assert (
        ledger.delegation_contracts.get(uid("task-release")).status is DelegationContractStatus.DONE
    )  # type: ignore[union-attr]
    assert ledger.teams.get(uid("team-release")).status is TeamStatus.ARCHIVED  # type: ignore[union-attr]


async def test_integrate_cap_interleave_keeps_verifying_so_authenticated_approve_lands(
    ledger: Ledger,
) -> None:
    await _open_acceptance_gate(ledger)
    pending = ledger.approvals.pending()
    assert len(pending) == 1
    contract = ledger.delegation_contracts.get(uid("task-release"))
    assert contract is not None and contract.status is DelegationContractStatus.VERIFYING
    accepted_run_id = contract.accepted_run_id

    leftover_id = uid("cap-interleave")
    ledger.wakes.enqueue(
        Wake(
            id=leftover_id,
            employee_id="lead",
            reason=WakeReason.CHILDREN_DONE,
            payload={"task_id": uid("task-release")},
        )
    )
    capped = _human_approval_scheduler(ledger, max_integrate_iterations=0)
    await capped.tick(_NOW)
    await capped.drain()

    kept = ledger.delegation_contracts.get(uid("task-release"))
    assert kept is not None and kept.status is DelegationContractStatus.VERIFYING
    assert kept.accepted_run_id == accepted_run_id
    dod = ledger.dod.get_for_task(uid("task-release"))
    assert dod is not None and dod.integration_ok is True and dod.status is DodStatus.PENDING
    assert ledger.tasks.get(uid("task-release")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert ledger.recovery_actions.active_for_source(uid("task-release")) is None
    still_pending = ledger.approvals.pending()
    assert len(still_pending) == 1 and still_pending[0].id == pending[0].id
    leftover = ledger.wakes.get(leftover_id)
    assert leftover is not None and leftover.status is WakeStatus.DONE

    GovernanceResolver(ledger).resolve_authenticated(
        pending[0].id,
        decision=ApprovalDecision.APPROVE,
        authorization=_authorization("cap-interleave"),
    )
    assert ledger.tasks.get(uid("task-release")).status is TaskStatus.DONE  # type: ignore[union-attr]
    assert (
        ledger.delegation_contracts.get(uid("task-release")).status is DelegationContractStatus.DONE
    )  # type: ignore[union-attr]


async def test_finish_delegation_parent_does_not_reenter_while_acceptance_pending(
    ledger: Ledger,
) -> None:
    await _open_acceptance_gate(ledger)
    contract = ledger.delegation_contracts.get(uid("task-release"))
    assert contract is not None and contract.status is DelegationContractStatus.VERIFYING
    accepted_run_id = contract.accepted_run_id
    task = ledger.tasks.get(uid("task-release"))
    lead = ledger.employees.get("lead")
    assert task is not None and lead is not None
    dod = ledger.dod.get_for_task(task.id)
    assert dod is not None and dod.status is DodStatus.PENDING and dod.integration_ok is True

    landing = await _human_approval_scheduler(ledger)._finish_delegation_parent(
        task=task,
        run_id="spoofed-later-run",
        verifier=ledger.dod.verifier_for_task(task.id),
        verdict=None,
        employee=lead,
        result=BeatOutcome(passed=True, outcome={}, summary="leftover integrate"),
        beat_runner=None,
        outcome_kind="subtree",
    )

    assert landing is None
    kept = ledger.delegation_contracts.get(task.id)
    assert kept is not None and kept.status is DelegationContractStatus.VERIFYING
    assert kept.accepted_run_id == accepted_run_id
    after = ledger.dod.get_for_task(task.id)
    assert after is not None and after.status is DodStatus.PENDING and after.integration_ok is True
    assert ledger.tasks.get(task.id).status is TaskStatus.BLOCKED  # type: ignore[union-attr]


async def test_authenticated_approve_fails_closed_when_contract_left_verifying(
    ledger: Ledger,
) -> None:
    await _open_acceptance_gate(ledger)
    pending = ledger.approvals.pending()
    assert len(pending) == 1
    ledger.delegation_contracts.update_status(
        uid("task-release"), DelegationContractStatus.INTEGRATING
    )

    with pytest.raises(GovernanceError, match="cannot close"):
        GovernanceResolver(ledger).resolve_authenticated(
            pending[0].id,
            decision=ApprovalDecision.APPROVE,
            authorization=_authorization("not-verifying"),
        )
    assert ledger.tasks.get(uid("task-release")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    kept = ledger.approvals.get(pending[0].id)
    assert kept is not None and kept.status is ApprovalStatus.PENDING
    contract = ledger.delegation_contracts.get(uid("task-release"))
    assert contract is not None and contract.status is DelegationContractStatus.INTEGRATING
    dod = ledger.dod.get_for_task(uid("task-release"))
    assert dod is not None and dod.status is DodStatus.PENDING
