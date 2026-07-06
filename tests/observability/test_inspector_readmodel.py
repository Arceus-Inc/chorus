"""The inspector read-model projections (spec 08 §3, spec 14 F1) — status / task / stuck.

Pure reads over the ledger: names resolved, liveness derived from the canonical
:func:`chorus.lifecycle.classify` (not byte-silence), blockers from the *unresolved* dependency
leaves. The inspector takes an injected clock so liveness (which compares run leases to ``now``) is
deterministic under test.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import Run, RunStatus, SqliteLedger, Task, TaskStatus
from chorus.observability import LedgerInspector
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def ledger() -> Iterator[SqliteLedger]:
    lg = SqliteLedger.open(":memory:")
    try:
        yield lg
    finally:
        lg.close()


def _inspector(ledger: SqliteLedger) -> LedgerInspector:
    return LedgerInspector(ledger, clock=lambda: _NOW)


def _seed(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="mgr", name="Moe", role="manager"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="mgr"))
    ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="mgr"))
    # active: in-progress with a live lease → healthy, and a running beat to count
    ledger.tasks.submit(
        Task(
            id="active", intent="ship it", status=TaskStatus.IN_PROGRESS, assignee_employee_id="ada"
        )
    )
    ledger.runs.create(
        Run(
            id="r_active",
            employee_id="ada",
            task_id="active",
            status=RunStatus.RUNNING,
            lease_expires_at=_NOW + timedelta(hours=1),
        )
    )
    # stuck: in-progress with no run/wake/monitor/recovery → stranded_in_progress (STALLED)
    ledger.tasks.submit(
        Task(
            id="stuck",
            intent="orphaned work",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="bob",
        )
    )
    # done: terminal, excluded from open/blocked
    ledger.tasks.submit(
        Task(id="done", intent="shipped", status=TaskStatus.DONE, assignee_employee_id="ada")
    )


def test_status_projects_the_company(ledger: SqliteLedger) -> None:
    _seed(ledger)
    status = _inspector(ledger).status()
    assert {e.id for e in status.employees} == {"mgr", "ada", "bob"}
    assert {(e.name, e.role) for e in status.employees if e.id == "ada"} == {("Ada", "engineer")}
    assert status.open_tasks == 2  # active + stuck; done is terminal
    assert status.running_beats == 1  # r_active
    assert {t.id for t in status.blocked} == {"stuck"}  # only the stalled one
    assert isinstance(status.open_incidents, tuple)


def test_stuck_lists_only_stalled_non_terminal_tasks(ledger: SqliteLedger) -> None:
    _seed(ledger)
    assert {t.id for t in _inspector(ledger).stuck()} == {"stuck"}


def test_task_resolves_name_liveness_and_unresolved_blockers(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.tasks.submit(
        Task(id="blk", intent="prereq", status=TaskStatus.TODO, assignee_employee_id="ada")
    )
    ledger.tasks.submit(
        Task(id="t", intent="the work", status=TaskStatus.IN_PROGRESS, assignee_employee_id="ada")
    )
    ledger.dependencies.add("t", "blk")
    view = _inspector(ledger).task("t")
    assert view.id == "t"
    assert view.assignee == "Ada"  # name resolved, not the id
    assert view.status is TaskStatus.IN_PROGRESS
    assert view.blockers == ("blk",)  # unresolved leaf
    assert view.liveness == "stalled"  # in-progress, no live run/wake → stranded


def test_task_done_blocker_is_not_a_blocker(ledger: SqliteLedger) -> None:
    ledger.tasks.submit(Task(id="blk", intent="prereq", status=TaskStatus.DONE))
    ledger.tasks.submit(Task(id="t", intent="the work", status=TaskStatus.TODO))
    ledger.dependencies.add("t", "blk")
    assert _inspector(ledger).task("t").blockers == ()  # resolved → not surfaced


def test_task_unknown_raises_keyerror(ledger: SqliteLedger) -> None:
    with pytest.raises(KeyError):
        _inspector(ledger).task("nope")
