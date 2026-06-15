"""RecoveryActionRepo — liveness-as-visibility (spec 01 Cluster B ``recovery_action``, spec 02).

The first-class "who owns making this unstuck." At most one *open* (active/escalated) recovery per
source task, and at most one per ``(source, cause, fingerprint)`` — both enforced by partial-unique
indexes. Resolving frees the source for a fresh recovery. Attempts are bounded.
"""

from __future__ import annotations

import sqlite3

import pytest

from chorus.ledger import (
    RecoveryAction,
    RecoveryKind,
    RecoveryOutcome,
    RecoveryStatus,
    SqliteLedger,
    Task,
)
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _task(ledger: SqliteLedger, tid: str = "t1") -> str:
    ledger.tasks.submit(Task(id=tid, intent="x"))
    return tid


def test_open_and_get(ledger: SqliteLedger) -> None:
    _task(ledger)
    ledger.employees.create(Employee(id="mgr", name="mgr", role="engineer"))
    opened = ledger.recovery_actions.open(
        RecoveryAction(
            id="rc1",
            source_task_id="t1",
            kind=RecoveryKind.STRANDED,
            cause="lease_expired",
            fingerprint="fp1",
            owner_employee_id="mgr",
            evidence={"run": "run9"},
            max_attempts=3,
        )
    )
    got = ledger.recovery_actions.get(opened.id)
    assert got is not None
    assert got.status is RecoveryStatus.ACTIVE
    assert got.kind is RecoveryKind.STRANDED
    assert got.source_task_id == "t1"
    assert got.cause == "lease_expired"
    assert got.owner_employee_id == "mgr"
    assert got.evidence == {"run": "run9"}
    assert got.attempt_count == 0
    assert got.resolved_at is None


def test_at_most_one_open_per_source(ledger: SqliteLedger) -> None:
    _task(ledger)
    ledger.recovery_actions.open(
        RecoveryAction(id="rc1", source_task_id="t1", kind=RecoveryKind.STRANDED, cause="c1")
    )
    with pytest.raises(sqlite3.IntegrityError):
        # different cause/fingerprint, same source → still blocked by recovery_active_source_uq
        ledger.recovery_actions.open(
            RecoveryAction(id="rc2", source_task_id="t1", kind=RecoveryKind.WORKSPACE, cause="c2")
        )


def test_active_for_source_tracks_open_state(ledger: SqliteLedger) -> None:
    _task(ledger)
    ledger.recovery_actions.open(
        RecoveryAction(id="rc1", source_task_id="t1", kind=RecoveryKind.STRANDED)
    )
    open_one = ledger.recovery_actions.active_for_source("t1")
    assert open_one is not None and open_one.id == "rc1"
    ledger.recovery_actions.escalate("rc1")
    # escalated is still "open"
    still = ledger.recovery_actions.active_for_source("t1")
    assert still is not None and still.status is RecoveryStatus.ESCALATED


def test_resolve_frees_the_source(ledger: SqliteLedger) -> None:
    _task(ledger)
    ledger.recovery_actions.open(
        RecoveryAction(id="rc1", source_task_id="t1", kind=RecoveryKind.STRANDED)
    )
    ledger.recovery_actions.resolve(
        "rc1", outcome=RecoveryOutcome.RESTORED, resolution_note="lease cleared"
    )
    got = ledger.recovery_actions.get("rc1")
    assert got is not None
    assert got.status is RecoveryStatus.RESOLVED
    assert got.outcome is RecoveryOutcome.RESTORED
    assert got.resolution_note == "lease cleared"
    assert got.resolved_at is not None
    assert ledger.recovery_actions.active_for_source("t1") is None
    # the source is free again
    reopened = ledger.recovery_actions.open(
        RecoveryAction(id="rc2", source_task_id="t1", kind=RecoveryKind.STRANDED)
    )
    assert reopened.status is RecoveryStatus.ACTIVE


def test_record_attempt_increments(ledger: SqliteLedger) -> None:
    _task(ledger)
    ledger.recovery_actions.open(
        RecoveryAction(id="rc1", source_task_id="t1", kind=RecoveryKind.STRANDED, max_attempts=3)
    )
    ledger.recovery_actions.record_attempt("rc1")
    got = ledger.recovery_actions.record_attempt("rc1")
    assert got.attempt_count == 2
    assert got.last_attempt_at is not None


def test_record_attempt_on_unknown_raises(ledger: SqliteLedger) -> None:
    with pytest.raises(KeyError):
        ledger.recovery_actions.record_attempt("ghost")
