"""Durable Lattice selection-seal outbox repository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from dream.contracts.strategy import LandedPhase

from chorus.ledger import (
    LatticeSelectionSeal,
    LatticeSelectionSealConflictError,
    Ledger,
    LedgerIntegrityError,
    Run,
    Task,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _seed_run(ledger: Ledger, suffix: str) -> tuple[str, str]:
    employee_id = uid(f"emp-{suffix}")
    task_id = uid(f"task-{suffix}")
    run_id = uid(f"run-{suffix}")
    ledger.employees.create(Employee(id=employee_id, name=employee_id, role="engineer"))
    ledger.tasks.submit(
        Task(id=task_id, intent="seal selected Lattice context", assignee_employee_id=employee_id)
    )
    ledger.runs.create(Run(id=run_id, employee_id=employee_id, task_id=task_id))
    return employee_id, run_id


def _seal(employee_id: str, run_id: str, *, phase: LandedPhase) -> LatticeSelectionSeal:
    return LatticeSelectionSeal(
        employee_id=employee_id,
        beat_run_id=run_id,
        outcome_phase=phase,
        landed_at=_NOW,
        next_attempt_at=_NOW,
    )


def test_exact_enqueue_is_idempotent_and_mismatched_replay_cannot_poison_it(ledger: Ledger) -> None:
    employee_id, run_id = _seed_run(ledger, "conflict")
    exact = _seal(employee_id, run_id, phase=LandedPhase.TERMINAL_PASS)

    first = ledger.lattice_selection_seals.enqueue(exact)
    replay = ledger.lattice_selection_seals.enqueue(exact)

    assert first == replay
    assert replay.attempt_count == 0
    assert replay.terminal_at is None

    mismatched = _seal(employee_id, run_id, phase=LandedPhase.NEEDS_REWORK)
    with pytest.raises(LatticeSelectionSealConflictError, match="immutable"):
        ledger.lattice_selection_seals.enqueue(mismatched)

    pending = ledger.lattice_selection_seals.get(run_id)
    assert pending is not None
    assert pending.outcome_phase is LandedPhase.TERMINAL_PASS
    assert pending.next_attempt_at == _NOW
    assert pending.terminal_at is None
    assert pending.last_error is None


def test_claim_retry_and_exact_replay_converge_to_one_stable_ack(ledger: Ledger) -> None:
    employee_id, run_id = _seed_run(ledger, "retry")
    ledger.lattice_selection_seals.enqueue(
        _seal(employee_id, run_id, phase=LandedPhase.TERMINAL_PASS)
    )

    claimed = ledger.lattice_selection_seals.claim_due(
        now=_NOW,
        lease_until=_NOW + timedelta(seconds=30),
        limit=1,
    )
    assert len(claimed) == 1
    assert claimed[0].attempt_count == 1
    assert (
        ledger.lattice_selection_seals.claim_due(
            now=_NOW + timedelta(seconds=29),
            lease_until=_NOW + timedelta(seconds=59),
            limit=1,
        )
        == ()
    )

    due_again = _NOW + timedelta(seconds=2)
    retried = ledger.lattice_selection_seals.mark_retry(
        claimed[0],
        error="temporary Lattice outage",
        next_attempt_at=due_again,
    )
    assert retried.last_error == "temporary Lattice outage"

    replay = ledger.lattice_selection_seals.claim_one(
        run_id,
        now=due_again,
        lease_until=due_again + timedelta(seconds=30),
    )
    assert replay is not None
    assert replay.attempt_count == 2

    first_ack = due_again + timedelta(seconds=1)
    sealed = ledger.lattice_selection_seals.mark_sealed(replay, sealed_at=first_ack)
    duplicate_ack = ledger.lattice_selection_seals.mark_sealed(
        replay,
        sealed_at=first_ack + timedelta(seconds=10),
    )
    assert sealed.sealed_at == first_ack
    assert duplicate_ack.sealed_at == first_ack
    assert duplicate_ack.next_attempt_at is None
    assert duplicate_ack.last_error is None


def test_stale_claim_cannot_overwrite_a_newer_attempt(ledger: Ledger) -> None:
    employee_id, run_id = _seed_run(ledger, "stale")
    ledger.lattice_selection_seals.enqueue(
        _seal(employee_id, run_id, phase=LandedPhase.TERMINAL_PASS)
    )
    stale = ledger.lattice_selection_seals.claim_one(
        run_id,
        now=_NOW,
        lease_until=_NOW + timedelta(seconds=30),
    )
    assert stale is not None
    ledger.lattice_selection_seals.mark_retry(
        stale,
        error="first failure",
        next_attempt_at=_NOW + timedelta(seconds=1),
    )
    current = ledger.lattice_selection_seals.claim_one(
        run_id,
        now=_NOW + timedelta(seconds=1),
        lease_until=_NOW + timedelta(seconds=31),
    )
    assert current is not None and current.attempt_count == 2

    after_stale_retry = ledger.lattice_selection_seals.mark_retry(
        stale,
        error="stale overwrite",
        next_attempt_at=_NOW + timedelta(days=1),
    )
    after_stale_terminal = ledger.lattice_selection_seals.mark_terminal(
        stale,
        error="stale conflict",
        terminal_at=_NOW + timedelta(seconds=2),
    )
    after_stale_ack = ledger.lattice_selection_seals.mark_sealed(
        stale,
        sealed_at=_NOW + timedelta(seconds=2),
    )

    for persisted in (after_stale_retry, after_stale_terminal, after_stale_ack):
        assert persisted.attempt_count == 2
        assert persisted.next_attempt_at == _NOW + timedelta(seconds=31)
        assert persisted.sealed_at is None
        assert persisted.terminal_at is None

    sealed = ledger.lattice_selection_seals.mark_sealed(
        current,
        sealed_at=_NOW + timedelta(seconds=3),
    )
    assert sealed.sealed_at == _NOW + timedelta(seconds=3)


def test_composite_run_fk_rejects_cross_company_link(pg_database: str) -> None:
    first_company = str(uuid.uuid4())
    second_company = str(uuid.uuid4())
    first = Ledger.open(pg_database, company_id=first_company)
    second = Ledger.open(pg_database, company_id=second_company)
    try:
        _employee_id, foreign_run_id = _seed_run(first, "tenant-a")
        second_employee = uid("tenant-b-employee")
        second.employees.create(Employee(id=second_employee, name=second_employee, role="engineer"))

        with pytest.raises(LedgerIntegrityError):
            second.lattice_selection_seals.enqueue(
                _seal(second_employee, foreign_run_id, phase=LandedPhase.TERMINAL_PASS)
            )
    finally:
        first.close()
        second.close()
