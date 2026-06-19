"""M3 — the load-bearing Reviewer through the kernel (spec M3, deterministic, no model).

A leaf ``agent_review`` deliverable is gated by a real reviewer beat: the kernel dispatches a read-only
Reviewer that calls ``submit_verdict``; approve lands the work ``done``, block routes per subsidiarity —
escalate to a manager parent (the rejected child drives the Slice-2 integrate), else bounded author
self-repair then a recovery card. Fake beat runners stand in for the worker / reviewer / manager.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from chorus.heartbeat import IntegrateContextPacket, Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import CapabilityService, ChildPlan, assign_task
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_employee import default_landers

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)


class _Runner:
    def __init__(self, working_dir: Path) -> None:
        self._wd = working_dir

    @property
    def working_dir(self) -> Path:
        return self._wd


class _Worker(_Runner):
    """A leaf worker that produces a passing deliverable (its DoD is the reviewer's verdict)."""

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        return BeatOutcome(passed=True, outcome={}, summary="produced", model="m")


class _Reviewer(_Runner):
    """A reviewer that records a verdict via the real CapabilityService. ``decide(task_id)`` → approve?"""

    def __init__(self, ledger: SqliteLedger, *, reviewer_id: str, decide: object, working_dir: Path) -> None:
        super().__init__(working_dir)
        self._ledger = ledger
        self._id = reviewer_id
        self._decide = decide

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        approve = bool(self._decide(task_id))  # type: ignore[operator]
        CapabilityService(self._ledger).record_verdict(
            task_id=task_id, run_id=str(run_id), reviewer_id=self._id, approve=approve, feedback="fb"
        )
        return BeatOutcome(passed=True, outcome={}, summary="reviewed", model="m")


class _Manager(_Runner):
    """Decompose on kickoff; on integrate, react when the kernel recommends it, else accept."""

    def __init__(self, ledger: SqliteLedger, *, parent: str, working_dir: Path) -> None:
        super().__init__(working_dir)
        self._ledger = ledger
        self._parent = parent

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        svc = CapabilityService(self._ledger)
        if not self._ledger.tasks.has_children(self._parent):
            svc.decompose(parent_id=self._parent, revision=str(run_id),
                          children=[ChildPlan(label="draft", intent="draft the spec", assignee="pen")])
            return BeatOutcome(passed=False, outcome={}, summary="delegated", model="m")
        if IntegrateContextPacket.recommended_for(self._ledger, self._parent) == "react":
            svc.submit_one(parent_id=self._parent, revision=str(run_id),
                           child=ChildPlan(label="redraft", intent="redraft the spec", assignee="paul"))
            return BeatOutcome(passed=False, outcome={}, summary="reacted to the rejection", model="m")
        return BeatOutcome(passed=True, outcome={}, summary="accepted", model="m")


class _Org:
    """A fake harness factory: a role-faithful fake runner per employee, plus the review seam."""

    def __init__(self, ledger: SqliteLedger, *, decide: object, root: Path, parent: str = "M") -> None:
        self._ledger = ledger
        self._decide = decide
        self._root = root
        self._parent = parent

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> object:
        return self._for(employee)

    def review_runner_for(self, reviewer: Employee, *, task_id: str, worktree_owner_id: str) -> object:
        return self._for(reviewer)

    def _for(self, employee: Employee) -> object:
        if employee.role == "reviewer":
            return _Reviewer(self._ledger, reviewer_id=employee.id, decide=self._decide, working_dir=self._root)
        if employee.role == "manager":
            return _Manager(self._ledger, parent=self._parent, working_dir=self._root)
        return _Worker(self._root)


def _sched(ledger: SqliteLedger, org: _Org, root: Path, *, max_review_rounds: int = 2) -> Scheduler:
    return Scheduler(
        ledger=ledger, workforce=LedgerWorkforce(ledger.employees), beat_runner_for=org,  # type: ignore[arg-type]
        roles=RoleRegistry.from_plugins(default_roles()),
        landers=default_landers(root, ledger=ledger),
        clock=lambda: _NOW, max_concurrent_runs=4, max_review_rounds=max_review_rounds,
    )


async def test_approve_lands_the_deliverable_done(ledger: SqliteLedger, tmp_path: Path) -> None:
    ledger.employees.create(Employee(id="pen", name="Pen", role="pm"))
    ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
    ledger.tasks.submit(Task(id="spec", intent="write the spec", status=TaskStatus.TODO))
    assign_task(ledger, "spec", "pen")
    org = _Org(ledger, decide=lambda _tid: True, root=tmp_path)
    sched = _sched(ledger, org, tmp_path)

    await sched.tick_once()
    await sched.drain()

    assert ledger.tasks.get("spec").status is TaskStatus.DONE  # type: ignore[union-attr]
    verdicts = [a for a in ledger.artifacts.list_for_task("spec") if a.type.value == "verdict"]
    assert len(verdicts) == 1 and verdicts[0].resource_ref["approve"] is True  # type: ignore[index]


async def test_no_reviewer_opens_a_recovery_card(ledger: SqliteLedger, tmp_path: Path) -> None:
    ledger.employees.create(Employee(id="pen", name="Pen", role="pm"))  # no reviewer hired
    ledger.tasks.submit(Task(id="spec", intent="write the spec", status=TaskStatus.TODO))
    assign_task(ledger, "spec", "pen")
    org = _Org(ledger, decide=lambda _tid: True, root=tmp_path)
    sched = _sched(ledger, org, tmp_path)

    await sched.tick_once()
    await sched.drain()

    assert ledger.tasks.get("spec").status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert ledger.recovery_actions.active_for_source("spec") is not None  # a human must verify it


async def test_standalone_block_self_repairs_then_opens_recovery(ledger: SqliteLedger, tmp_path: Path) -> None:
    ledger.employees.create(Employee(id="pen", name="Pen", role="pm"))
    ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
    ledger.tasks.submit(Task(id="spec", intent="write the spec", status=TaskStatus.TODO))
    assign_task(ledger, "spec", "pen")
    org = _Org(ledger, decide=lambda _tid: False, root=tmp_path)  # always blocks
    sched = _sched(ledger, org, tmp_path, max_review_rounds=1)

    for _ in range(6):  # produce → block → self-repair (≤cap) → … → recovery card past the cap
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get("spec").status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert ledger.recovery_actions.active_for_source("spec") is not None  # bounded, then a human


async def test_manager_parented_block_escalates_and_manager_reacts(ledger: SqliteLedger, tmp_path: Path) -> None:
    # The headline: a reviewer block on a manager's child becomes a child outcome the Slice-2 manager
    # reacts to. draft is blocked → REJECTED → manager integrate sees `react` → submits redraft →
    # redraft is approved → subtree completes → manager accepts → goal done.
    ledger.employees.create(Employee(id="moe", name="Moe", role="manager"))
    ledger.employees.create(Employee(id="pen", name="Pen", role="pm", reports_to="moe"))
    ledger.employees.create(Employee(id="paul", name="Paul", role="pm", reports_to="moe"))
    ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
    ledger.tasks.submit(Task(id="M", intent="ship the spec", status=TaskStatus.TODO))
    assign_task(ledger, "M", "moe")

    def decide(task_id: str) -> bool:
        task = ledger.tasks.get(task_id)
        return task is not None and task.origin_fingerprint != "draft"  # block only the first draft

    org = _Org(ledger, decide=decide, root=tmp_path, parent="M")
    sched = _sched(ledger, org, tmp_path)

    for _ in range(12):
        await sched.tick_once()
        await sched.drain()

    children = {c.origin_fingerprint: c for c in ledger.tasks.children("M")}
    assert children["draft"].status is TaskStatus.REJECTED  # reviewer blocked it → terminal-rejected
    assert children["redraft"].status is TaskStatus.DONE  # the manager's fix, approved on review
    assert ledger.tasks.get("M").status is TaskStatus.DONE  # type: ignore[union-attr]  # integrated
