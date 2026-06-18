"""M3 Slice 1 — the manager's two-phase lifecycle through the kernel (spec M3 §5, deterministic).

A decompose beat is a *fifth* outcome: it neither passed, failed its DoD, errored, nor cancelled — it
**succeeded by delegating**, so the parent is PARKED (``blocked``, waiting on its children), never
stranded onto the recovery ladder. When the children finish, ``children_done`` re-invokes the manager
and the kernel mechanically integrates (all children terminal ⇒ ``done``). No model: a fake beat runner
stands in for the manager (decomposing via the live :class:`CapabilityService`) and the engineers.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.heartbeat import Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import CapabilityService, ChildPlan, assign_task
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)


class _TeamBeat:
    """A fake beat: on the manager's parent it decomposes once (via the real CapabilityService) into
    two assigned children; every other beat (the children, the manager's integrate re-invocation) just
    passes. The parent beats return ``passed=False`` to prove park/integrate ignore the dream verdict."""

    def __init__(self, ledger: SqliteLedger, *, parent: str) -> None:
        self._ledger = ledger
        self._parent = parent
        self.ran: list[str] = []

    async def run_task(
        self, *, task_id: str, intent: str, verification: object = (),
        observer: object = None, run_id: str | None = None,
    ) -> BeatOutcome:
        self.ran.append(task_id)
        if task_id == self._parent:
            if not self._ledger.tasks.has_children(self._parent):  # the decompose beat
                CapabilityService(self._ledger).decompose(
                    parent_id=self._parent, revision=str(run_id), children=[
                        ChildPlan(label="api", intent="build the api", assignee="ada"),
                        ChildPlan(label="ui", intent="build the ui", assignee="bob", depends_on=("api",)),
                    ],
                )
            return BeatOutcome(passed=False, outcome={}, summary="delegated", model="m")
        return BeatOutcome(passed=True, outcome={}, summary="ok", model="m")  # an engineer child


def _team(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="mgr", name="Moe", role="manager"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.employees.create(Employee(id="bob", name="Bob", role="engineer"))


def _sched(ledger: SqliteLedger, beat: _TeamBeat) -> Scheduler:
    return Scheduler(
        ledger=ledger, workforce=LedgerWorkforce(ledger.employees), beat_runner=beat,
        roles=RoleRegistry.from_plugins(default_roles()), clock=lambda: _NOW, max_concurrent_runs=4,
    )


async def test_decompose_beat_parks_the_parent_not_strands_it(ledger: SqliteLedger) -> None:
    _team(ledger)
    ledger.tasks.submit(Task(id="M", intent="ship the feature", status=TaskStatus.TODO))
    assign_task(ledger, "M", "mgr")
    beat = _TeamBeat(ledger, parent="M")
    sched = _sched(ledger, beat)

    await sched.tick_once()  # the manager's decompose beat
    await sched.drain()

    parent = ledger.tasks.get("M")
    assert parent is not None and parent.status is TaskStatus.BLOCKED  # PARKED, not failed
    assert ledger.recovery_actions.active_for_source("M") is None  # never stranded onto recovery
    # the two children exist, assigned, gating the parent
    assert set(ledger.dependencies.unresolved_blockers("M")) and not ledger.tasks.all_children_terminal("M")


async def test_full_loop_decompose_then_children_then_integrate_to_done(ledger: SqliteLedger) -> None:
    _team(ledger)
    ledger.tasks.submit(Task(id="M", intent="ship the feature", status=TaskStatus.TODO))
    assign_task(ledger, "M", "mgr")
    beat = _TeamBeat(ledger, parent="M")
    sched = _sched(ledger, beat)

    for _ in range(6):  # decompose → api → ui → children_done → integrate
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get("M").status is TaskStatus.DONE  # type: ignore[union-attr]  # integrated
    assert ledger.tasks.all_children_terminal("M")  # the whole subtree landed
    assert "M" in beat.ran and beat.ran.count("M") >= 2  # decompose beat + integrate beat
