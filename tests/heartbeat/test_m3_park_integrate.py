"""M3 — the manager's two-phase lifecycle through the kernel (spec M3 §5, deterministic).

A decompose beat is a *fifth* outcome: it neither passed, failed its DoD, errored, nor cancelled — it
**succeeded by delegating**, so the parent is PARKED (``blocked``, waiting on its children), never
stranded onto the recovery ladder. When the children finish, ``children_done`` re-invokes the manager
with an integrate context packet; the manager can accept the subtree or submit/assign one bounded
follow-up. No model: a fake beat runner stands in for the manager (decomposing via the live
:class:`CapabilityService`) and the engineers.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.heartbeat import IntegrateContextPacket, Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import CapabilityService, ChildPlan, assign_task
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_employee import default_landers

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
        self.integrate_packets: list[IntegrateContextPacket] = []
        self.working_dir = None

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
            assert self.working_dir is not None
            self.integrate_packets.append(IntegrateContextPacket.read(self.working_dir))
            return BeatOutcome(passed=True, outcome={}, summary="accepted subtree", model="m")
        return BeatOutcome(passed=True, outcome={}, summary="ok", model="m")  # an engineer child


def _team(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="mgr", name="Moe", role="manager"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="mgr"))
    ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="mgr"))


def _objective_roles() -> RoleRegistry:
    """Default roles, but the engineer is gated by an objective command — these tests exercise park /
    integrate, not the engineer's reviewed-build review gate (covered in test_m3_review)."""
    from chorus.outcomes import Verifier
    from chorus.roles._plugin import RolePlugin

    base = default_roles()
    engineer = next(p for p in base if p.name == "engineer")
    others = tuple(p for p in base if p.name != "engineer")
    objective = RolePlugin(
        name="engineer", manifest=engineer.manifest,
        dod_generator=lambda intent: Verifier.command("true", artifact_class="pr"),
        outcome_kind=engineer.outcome_kind,
    )
    return RoleRegistry.from_plugins((*others, objective))


def _sched(ledger: SqliteLedger, beat: _TeamBeat, *, tmp_path: object = None) -> Scheduler:
    from pathlib import Path

    root = Path(str(tmp_path)) if tmp_path is not None else Path(".")
    beat.working_dir = root
    return Scheduler(
        ledger=ledger, workforce=LedgerWorkforce(ledger.employees), beat_runner=beat,
        roles=_objective_roles(),
        landers=default_landers(root, ledger=ledger),  # the manager lands a subtree artifact on integrate
        clock=lambda: _NOW, max_concurrent_runs=4,
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


async def test_full_loop_decompose_then_children_then_integrate_to_done(
    ledger: SqliteLedger, tmp_path: object
) -> None:
    _team(ledger)
    ledger.tasks.submit(Task(id="M", intent="ship the feature", status=TaskStatus.TODO))
    assign_task(ledger, "M", "mgr")
    beat = _TeamBeat(ledger, parent="M")
    sched = _sched(ledger, beat, tmp_path=tmp_path)

    for _ in range(6):  # decompose → api → ui → children_done → integrate
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get("M").status is TaskStatus.DONE  # type: ignore[union-attr]  # integrated
    assert ledger.tasks.all_children_terminal("M")  # the whole subtree landed
    assert beat.ran.count("M") == 2  # decompose beat, then real integrate beat
    assert len(beat.integrate_packets) == 1
    assert {child.assignee for child in beat.integrate_packets[0].children} == {"ada", "bob"}
    # the ManagerLander recorded the subtree as the manager's primary deliverable
    subtree = next(
        a for a in ledger.artifacts.list_for_task("M")
        if a.resource_ref is not None and a.resource_ref.get("kind") == "subtree"
    )
    assert {c["id"] for c in subtree.resource_ref["children"]} == {  # type: ignore[union-attr,index]
        c.id for c in ledger.tasks.children("M")
    }


class _AdaptiveBeat:
    """Decompose on kickoff; on integrate #1 submit ONE follow-up child; on integrate #2 accept."""

    def __init__(self, ledger: SqliteLedger, *, parent: str) -> None:
        self._ledger = ledger
        self._parent = parent
        self.ran: list[str] = []
        self.integrate_packets: list[IntegrateContextPacket] = []
        self.working_dir: object = None
        self._integrates = 0

    async def run_task(
        self, *, task_id: str, intent: str, verification: object = (),
        observer: object = None, run_id: str | None = None,
    ) -> BeatOutcome:
        self.ran.append(task_id)
        svc = CapabilityService(self._ledger)
        if task_id != self._parent:
            return BeatOutcome(passed=True, outcome={}, summary="ok", model="m")  # an engineer child
        if not self._ledger.tasks.has_children(self._parent):  # kickoff beat
            svc.decompose(parent_id=self._parent, revision=str(run_id), children=[
                ChildPlan(label="api", intent="api", assignee="ada"),
                ChildPlan(label="ui", intent="ui", assignee="bob"),
            ])
            return BeatOutcome(passed=False, outcome={}, summary="delegated", model="m")
        self._integrates += 1
        from pathlib import Path
        self.integrate_packets.append(IntegrateContextPacket.read(Path(str(self.working_dir))))
        if self._integrates == 1:  # react: one concrete follow-up
            svc.submit_one(parent_id=self._parent, revision=str(run_id),
                           child=ChildPlan(label="polish", intent="polish", assignee="ada"))
            return BeatOutcome(passed=False, outcome={}, summary="submitted follow-up", model="m")
        return BeatOutcome(passed=True, outcome={}, summary="accepted", model="m")  # integrate #2


class _AlwaysSubmitBeat:
    """A misbehaving manager: decompose on kickoff, then submit a fresh follow-up on EVERY integrate."""

    def __init__(self, ledger: SqliteLedger, *, parent: str) -> None:
        self._ledger = ledger
        self._parent = parent
        self.ran: list[str] = []
        self.working_dir: object = None
        self._n = 0

    async def run_task(
        self, *, task_id: str, intent: str, verification: object = (),
        observer: object = None, run_id: str | None = None,
    ) -> BeatOutcome:
        self.ran.append(task_id)
        svc = CapabilityService(self._ledger)
        if task_id != self._parent:
            return BeatOutcome(passed=True, outcome={}, summary="ok", model="m")
        if not self._ledger.tasks.has_children(self._parent):
            svc.decompose(parent_id=self._parent, revision=str(run_id),
                          children=[ChildPlan(label="c0", intent="c0", assignee="ada")])
            return BeatOutcome(passed=False, outcome={}, summary="delegated", model="m")
        self._n += 1
        svc.submit_one(parent_id=self._parent, revision=str(run_id),
                       child=ChildPlan(label=f"more{self._n}", intent="more", assignee="ada"))
        return BeatOutcome(passed=False, outcome={}, summary="never accepts", model="m")


def _adaptive_sched(ledger: SqliteLedger, beat: object, root: object, *, cap: int = 3) -> Scheduler:
    from pathlib import Path

    beat.working_dir = Path(str(root))  # type: ignore[attr-defined]
    return Scheduler(
        ledger=ledger, workforce=LedgerWorkforce(ledger.employees), beat_runner=beat,  # type: ignore[arg-type]
        roles=_objective_roles(),
        landers=default_landers(Path(str(root)), ledger=ledger),
        clock=lambda: _NOW, max_concurrent_runs=4, max_integrate_iterations=cap,
    )


async def test_adaptive_integrate_submits_a_follow_up_then_re_integrates_to_done(
    ledger: SqliteLedger, tmp_path: object
) -> None:
    _team(ledger)
    ledger.tasks.submit(Task(id="M", intent="ship the feature", status=TaskStatus.TODO))
    assign_task(ledger, "M", "mgr")
    beat = _AdaptiveBeat(ledger, parent="M")
    sched = _adaptive_sched(ledger, beat, tmp_path)

    for _ in range(12):  # kickoff → api,ui → integrate#1 (submit polish) → polish → integrate#2 (accept)
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get("M").status is TaskStatus.DONE  # type: ignore[union-attr]
    assert len(ledger.tasks.children("M")) == 3  # api, ui, + the submitted polish
    assert ledger.tasks.all_children_terminal("M")
    # the manager REACTED: kickoff + integrate#1 (submitted) + integrate#2 (accepted) = 3 model beats
    assert beat.ran.count("M") == 3
    # the real iteration count is threaded into the packet
    assert [p.iteration for p in beat.integrate_packets] == [1, 2]


async def test_adaptive_integrate_is_bounded_by_the_iteration_cap(
    ledger: SqliteLedger, tmp_path: object
) -> None:
    _team(ledger)
    ledger.tasks.submit(Task(id="M", intent="ship the feature", status=TaskStatus.TODO))
    assign_task(ledger, "M", "mgr")
    beat = _AlwaysSubmitBeat(ledger, parent="M")
    sched = _adaptive_sched(ledger, beat, tmp_path, cap=2)  # bound the loop at 2 adaptive integrates

    for _ in range(30):  # a manager that never accepts must still terminate
        await sched.tick_once()
        await sched.drain()

    # the kernel forced acceptance at the cap — the subtree is done, not looping forever
    assert ledger.tasks.get("M").status is TaskStatus.DONE  # type: ignore[union-attr]
    # kickoff + exactly cap(=2) adaptive integrate beats; the 3rd integrate was capped (mechanical, no beat)
    assert beat.ran.count("M") == 3
