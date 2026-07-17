"""M2 acceptance: two employees, a dependency DAG, concurrency, and a hard budget breach (spec 11 §M2).

The milestone proof, end to end through the scheduler:
- ``B depends_on A`` → B is **withheld** until A is ``done``, then the ``deps_resolved`` wake dispatches B.
- two employees' beats run **concurrently** under the concurrency cap (and the cap actually limits it).
- a hard budget breach **pauses** the scope so the next dispatch is gated (the breach "kills" future work).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.budgets import BudgetEnforcer
from chorus.heartbeat import Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import Ledger, Task, TaskStatus, Wake, WakeReason
from chorus.ledger._models import BudgetPolicy, BudgetScope
from chorus.lifecycle import assign_task
from chorus.testing import uid
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)


class _Beat:
    """A :class:`BeatRunner` that passes and records the order tasks ran in."""

    def __init__(self, *, cost_cents: int = 0) -> None:
        self.ran: list[str] = []
        self._cost = cost_cents

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        self.ran.append(task_id)
        return BeatOutcome(passed=True, outcome={}, summary="ok", cost_cents=self._cost, model="m")


def _two_engineers(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="E1", role="engineer"))
    ledger.employees.create(Employee(id=uid("e2"), name="E2", role="engineer"))


def _sched(
    ledger: Ledger, beat: _Beat, *, cap: int = 4, enforcer: BudgetEnforcer | None = None
) -> Scheduler:
    return Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=beat,
        budget_enforcer=enforcer,
        clock=lambda: _NOW,
        max_concurrent_runs=cap,
    )


async def test_dependent_is_withheld_then_dispatched_on_deps_resolved(ledger: Ledger) -> None:
    _two_engineers(ledger)
    ledger.tasks.submit(Task(id=uid("A"), intent="ship A", status=TaskStatus.TODO))
    ledger.tasks.submit(Task(id=uid("B"), intent="ship B", status=TaskStatus.TODO))
    ledger.dependencies.add(uid("B"), uid("A"))  # B depends on A
    assign_task(ledger, uid("A"), uid("e1"))
    assign_task(ledger, uid("B"), uid("e2"))  # B is assigned + woken, but blocked by A
    beat = _Beat()
    sched = _sched(ledger, beat)

    await sched.tick_once()  # pulse 1
    await sched.drain()
    assert beat.ran == [uid("A")]  # A ran; B was WITHHELD (its blocker is unresolved)
    assert ledger.tasks.get(uid("A")).status is TaskStatus.DONE  # type: ignore[union-attr]

    await sched.tick_once()  # pulse 2: A's completion fired deps_resolved for B
    await sched.drain()
    assert uid("B") in beat.ran  # now B dispatches — the dependency edge gated it as data


async def test_two_employees_run_concurrently_under_the_cap(ledger: Ledger) -> None:
    _two_engineers(ledger)
    ledger.tasks.submit(Task(id=uid("A"), intent="a", status=TaskStatus.TODO))
    ledger.tasks.submit(Task(id=uid("B"), intent="b", status=TaskStatus.TODO))  # independent
    assign_task(ledger, uid("A"), uid("e1"))
    assign_task(ledger, uid("B"), uid("e2"))
    beat = _Beat()
    sched = _sched(ledger, beat, cap=2)

    await sched.tick_once()  # cap=2 → both employees' beats dispatch in one pulse
    await sched.drain()
    assert set(beat.ran) == {uid("A"), uid("B")}


async def test_concurrency_cap_limits_dispatch(ledger: Ledger) -> None:
    _two_engineers(ledger)
    ledger.tasks.submit(Task(id=uid("A"), intent="a", status=TaskStatus.TODO))
    ledger.tasks.submit(Task(id=uid("B"), intent="b", status=TaskStatus.TODO))
    assign_task(ledger, uid("A"), uid("e1"))
    assign_task(ledger, uid("B"), uid("e2"))
    beat = _Beat()
    sched = _sched(ledger, beat, cap=1)

    await sched.tick_once()  # cap=1 → only one beat this pulse; the other waits
    await sched.drain()
    assert len(beat.ran) == 1


async def test_stale_wake_for_a_done_task_is_drained_not_requeued(ledger: Ledger) -> None:
    # A manager fans out several deps_resolved/children_done wakes per task; once one drives the
    # integrate the rest point at a now-done task. Left queued they fail checkout every tick and clog
    # the employee's one-beat-per-pulse slot, starving its other work. They must be DRAINED.
    _two_engineers(ledger)
    ledger.tasks.submit(
        Task(id=uid("D"), intent="already integrated", assignee_employee_id=uid("e1"))
    )
    ledger.tasks.set_status(uid("D"), TaskStatus.DONE)
    ledger.tasks.submit(Task(id=uid("T"), intent="real pending work", status=TaskStatus.TODO))
    # The stale wake for the DONE task sits ahead of the live one in e1's queue.
    ledger.wakes.enqueue(
        Wake(
            id=uid("stale"),
            employee_id=uid("e1"),
            reason=WakeReason.CHILDREN_DONE,
            payload={"task_id": uid("D")},
        )
    )
    assign_task(ledger, uid("T"), uid("e1"))  # the live wake
    beat = _Beat()
    sched = _sched(ledger, beat)

    await sched.tick_once()
    await sched.drain()

    queued = {w.payload.get("task_id") for w in ledger.wakes.queued()}
    assert uid("D") not in queued  # the stale wake was drained, not re-queued
    assert (
        uid("T") in beat.ran
    )  # ...so the live work still dispatched despite the stale wake ahead of it


async def test_hard_budget_breach_pauses_the_scope(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="E1", role="engineer"))
    ledger.budget_policies.create(
        BudgetPolicy(id=uid("bp1"), scope_type=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    )
    ledger.tasks.submit(Task(id=uid("A"), intent="a", status=TaskStatus.TODO))
    assign_task(ledger, uid("A"), uid("e1"))
    enforcer = BudgetEnforcer(ledger, company_id="acme")
    beat = _Beat(cost_cents=150)  # one beat blows the cap
    sched = _sched(ledger, beat, enforcer=enforcer)

    await sched.tick_once()
    await sched.drain()
    assert beat.ran == [uid("A")]  # the beat ran
    assert (
        enforcer.invocation_block(uid("e1"), now=_NOW) is not None
    )  # ...and tripped the hard stop → scope paused
