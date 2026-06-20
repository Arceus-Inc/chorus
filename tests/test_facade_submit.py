"""The facade intake verb (spec 14 F2) — ``submit`` creates a depth-0 task, optionally wired.

The high-level front door: ``org.submit("build a login page", assignee="moe")`` creates the task and
hands it to its owner in one call. Optional ``dod`` / ``depends_on`` / ``priority`` wire the rest.
Fail-closed: an unknown assignee raises before anything is written.
"""

from __future__ import annotations

import pytest

from chorus.errors import UnknownEmployee
from chorus.facade import Caps, Chorus
from chorus.ledger import SqliteLedger, TaskPriority, TaskStatus
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
        ledger.employees.create(Employee(id="moe", name="Moe", role="manager"))
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
