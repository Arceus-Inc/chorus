"""M3 — the load-bearing Reviewer through the kernel (spec M3, deterministic, no model).

A leaf ``agent_review`` deliverable is gated by a real reviewer beat: the kernel dispatches a read-only
Reviewer that calls ``submit_verdict``; approve lands the work ``done``, block routes per subsidiarity —
escalate to a manager parent (the rejected child drives the Slice-2 integrate), else bounded author
self-repair then a recovery card. Fake beat runners stand in for the worker / reviewer / manager.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chorus.heartbeat import IntegrateContextPacket, Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import CapabilityService, ChildPlan, assign_task
from chorus.recovery import reconcile
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
    """A reviewer that records a verdict via the real CapabilityService. ``decide(task_id)`` → approve?

    ``verify_command`` (when set) is reported on the verdict — the kernel runs it as the objective floor.
    """

    def __init__(self, ledger: SqliteLedger, *, reviewer_id: str, decide: object, working_dir: Path,
                 verify_command: str = "") -> None:
        super().__init__(working_dir)
        self._ledger = ledger
        self._id = reviewer_id
        self._decide = decide
        self._verify_command = verify_command

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        approve = bool(self._decide(task_id))  # type: ignore[operator]
        CapabilityService(self._ledger).record_verdict(
            task_id=task_id, run_id=str(run_id), reviewer_id=self._id, approve=approve, feedback="fb",
            verify_command=self._verify_command,
        )
        return BeatOutcome(passed=True, outcome={}, summary="reviewed", model="m")


class _SilentReviewer(_Runner):
    """A reviewer that runs but never calls submit_verdict (renders no verdict)."""

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        return BeatOutcome(passed=True, outcome={}, summary="said nothing", model="m")


class _SlowReviewer(_Reviewer):
    """A reviewer whose beat spans several event-loop turns, so the ``run()`` loop ticks (and RECOVER
    sweeps) *while the review run is in flight* — the genuine ``run_forever`` condition, not a hand-poked
    reconcile. The approved deliverable must still land ``done``."""

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        for _ in range(6):
            await asyncio.sleep(0)  # yield: let run()'s pulses interleave with the in-flight review
        return await super().run_task(
            task_id=task_id, intent=intent, verification=verification, observer=observer, run_id=run_id
        )


class _ReconcilingReviewer(_Reviewer):
    """A reviewer that runs a RECOVER sweep mid-review before recording its verdict.

    The review beat runs inline inside the author's beat; under ``run_forever`` the tick loop keeps
    firing RECOVER (``reconcile``) while the reviewer awaits the model. This reproduces that: the review
    run must carry a lease, or the sweep reaps it as crash debris (a ``RUNNING`` run with a null lease)
    and strands the approved work — the bug that only surfaces under continuous ticking, never tick+drain.
    """

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        reconcile(self._ledger, now=_NOW + timedelta(seconds=1))  # a concurrent tick's RECOVER step
        return await super().run_task(
            task_id=task_id, intent=intent, verification=verification, observer=observer, run_id=run_id
        )


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

    def __init__(self, ledger: SqliteLedger, *, decide: object, root: Path, parent: str = "M",
                 silent: bool = False, verify_command: str = "", reconciling: bool = False,
                 slow_review: bool = False) -> None:
        self._ledger = ledger
        self._decide = decide
        self._root = root
        self._parent = parent
        self._silent = silent
        self._verify_command = verify_command
        self._reconciling = reconciling
        self._slow_review = slow_review

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> object:
        return self._for(employee)

    def review_runner_for(self, reviewer: Employee, *, task_id: str, worktree_owner_id: str) -> object:
        return self._for(reviewer)

    def _for(self, employee: Employee) -> object:
        if employee.role == "reviewer":
            if self._silent:
                return _SilentReviewer(self._root)
            reviewer_cls = _Reviewer
            if self._reconciling:
                reviewer_cls = _ReconcilingReviewer
            elif self._slow_review:
                reviewer_cls = _SlowReviewer
            return reviewer_cls(self._ledger, reviewer_id=employee.id, decide=self._decide,
                                working_dir=self._root, verify_command=self._verify_command)
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


async def test_review_run_survives_a_concurrent_recover_sweep(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    """A RECOVER sweep firing while the inline reviewer beat is in flight must not reap it.

    The review beat runs inside the author's beat; under ``run_forever`` the tick loop keeps sweeping
    stale leases (``reconcile``) while the reviewer awaits the model. Reproduced here by reconciling
    mid-review: an approved deliverable must still land ``done`` (the review run carries a lease, so the
    sweep leaves it alone) — not be stranded as reaped crash debris. Regression for the run_forever bug.
    """
    ledger.employees.create(Employee(id="pen", name="Pen", role="pm"))
    ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
    ledger.tasks.submit(Task(id="spec", intent="write the spec", status=TaskStatus.TODO))
    assign_task(ledger, "spec", "pen")
    org = _Org(ledger, decide=lambda _tid: True, root=tmp_path, reconciling=True)
    sched = _sched(ledger, org, tmp_path)

    await sched.tick_once()
    await sched.drain()

    assert ledger.tasks.get("spec").status is TaskStatus.DONE  # type: ignore[union-attr]


async def test_review_run_carries_a_lease(ledger: SqliteLedger, tmp_path: Path) -> None:
    """The in-flight review run is leased like any other beat — so the stale-run reaper (a concurrent
    RECOVER, or another Arceus worker) never mistakes it for crash debris (a null lease) and reaps it."""
    ledger.employees.create(Employee(id="pen", name="Pen", role="pm"))
    ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
    ledger.tasks.submit(Task(id="spec", intent="write the spec", status=TaskStatus.TODO))
    assign_task(ledger, "spec", "pen")
    org = _Org(ledger, decide=lambda _tid: True, root=tmp_path)
    sched = _sched(ledger, org, tmp_path)

    await sched.tick_once()
    await sched.drain()

    review_runs = [r for r in ledger.runs.for_task("spec") if r.id.startswith("rev_")]
    assert review_runs and all(r.lease_expires_at is not None for r in review_runs)


async def test_run_forever_lands_a_reviewed_deliverable_done(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    """The production driver ``run()`` (continuous pulses, no per-pulse drain) lands an approved review.

    Unlike tick+drain, ``run()`` keeps ticking — RECOVER and dispatch fire on every pulse — while a beat
    is in flight. With a reviewer beat that spans several pulses, this exercises the real ``run_forever``
    interleaving end to end and asserts the deliverable still reaches ``done``.
    """
    ledger.employees.create(Employee(id="pen", name="Pen", role="pm"))
    ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
    ledger.tasks.submit(Task(id="spec", intent="write the spec", status=TaskStatus.TODO))
    assign_task(ledger, "spec", "pen")
    org = _Org(ledger, decide=lambda _tid: True, root=tmp_path, slow_review=True)

    pulses = 0
    _SAFETY_CAP = 2000  # an instant injected sleep lets run() spin many no-op pulses; cap so a genuine
    # stall (the deliverable never settling) fails fast instead of looping forever.

    async def _sleep(_seconds: float) -> None:
        nonlocal pulses
        pulses += 1
        await asyncio.sleep(0)  # one real yield so the in-flight review can advance between pulses
        if pulses > _SAFETY_CAP or ledger.tasks.get("spec") is None or (
            (task := ledger.tasks.get("spec")) is not None and task.status is TaskStatus.DONE
        ):
            sched.stop()

    sched = Scheduler(
        ledger=ledger, workforce=LedgerWorkforce(ledger.employees), beat_runner_for=org,  # type: ignore[arg-type]
        roles=RoleRegistry.from_plugins(default_roles()),
        landers=default_landers(tmp_path, ledger=ledger),
        clock=lambda: _NOW, max_concurrent_runs=4, sleep=_sleep,
    )
    await sched.run()

    # The invariant under run_forever: the approved deliverable settles ``done`` (it is never stranded by
    # RECOVER/dispatch firing mid-review). The pulse count itself is not meaningful (instant sleep spins).
    assert pulses <= _SAFETY_CAP, "run() never settled the reviewed deliverable"
    assert ledger.tasks.get("spec").status is TaskStatus.DONE  # type: ignore[union-attr]


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


async def test_a_reviewer_that_renders_no_verdict_opens_a_recovery_card(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    # The deliverable must never silently pass, nor loop forever, when the reviewer beat fails to
    # render a verdict (the live bug this guards): the task blocks and a human is paged.
    ledger.employees.create(Employee(id="pen", name="Pen", role="pm"))
    ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
    ledger.tasks.submit(Task(id="spec", intent="write the spec", status=TaskStatus.TODO))
    assign_task(ledger, "spec", "pen")
    org = _Org(ledger, decide=lambda _tid: True, root=tmp_path, silent=True)
    sched = _sched(ledger, org, tmp_path)

    for _ in range(4):
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get("spec").status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert ledger.recovery_actions.active_for_source("spec") is not None
    assert not [a for a in ledger.artifacts.list_for_task("spec") if a.type.value == "verdict"]  # no empty verdict


def _reviewed_build_task(ledger: SqliteLedger) -> None:
    from chorus.outcomes import Verifier

    ledger.employees.create(Employee(id="dev", name="Dev", role="engineer"))
    ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
    ledger.tasks.submit(Task(id="code", intent="build the widget", status=TaskStatus.TODO))
    assign_task(ledger, "code", "dev")
    ledger.dod.create("code", Verifier.reviewed_build(artifact_class="pr"))  # the engineer's gate


async def test_reviewed_build_approve_and_passing_command_lands_done(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    _reviewed_build_task(ledger)
    org = _Org(ledger, decide=lambda _tid: True, root=tmp_path, verify_command="true")  # exit 0
    sched = _sched(ledger, org, tmp_path)

    await sched.tick_once()
    await sched.drain()

    assert ledger.tasks.get("code").status is TaskStatus.DONE  # type: ignore[union-attr]
    dod = ledger.dod.get_for_task("code")
    assert dod is not None and dod.verdict is not None and dod.verdict["build_passed"] is True


async def test_reviewed_build_failing_command_does_not_land(ledger: SqliteLedger, tmp_path: Path) -> None:
    # The reviewer liked the diff, but the kernel-run command fails → the build is NOT done (the floor
    # is un-rationalizable). Standalone → bounded self-repair, never a silent pass.
    _reviewed_build_task(ledger)
    org = _Org(ledger, decide=lambda _tid: True, root=tmp_path, verify_command="false")  # exit 1
    sched = _sched(ledger, org, tmp_path, max_review_rounds=1)

    for _ in range(6):
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get("code").status is not TaskStatus.DONE  # type: ignore[union-attr]
    dod = ledger.dod.get_for_task("code")
    assert dod is not None and dod.verdict is not None and dod.verdict["build_passed"] is False
    assert ledger.recovery_actions.active_for_source("code") is not None  # bounded → human


async def test_reviewed_build_quality_block_skips_the_command(ledger: SqliteLedger, tmp_path: Path) -> None:
    _reviewed_build_task(ledger)
    # the reviewer blocks on quality; the command never runs (no build_passed recorded)
    org = _Org(ledger, decide=lambda _tid: False, root=tmp_path, verify_command="true")
    sched = _sched(ledger, org, tmp_path, max_review_rounds=1)

    for _ in range(4):
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get("code").status is not TaskStatus.DONE  # type: ignore[union-attr]
    dod = ledger.dod.get_for_task("code")
    assert dod is not None and dod.verdict is not None and "build_passed" not in dod.verdict


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


def test_worktree_file_manifest_lists_the_files_a_listless_reviewer_cannot_see(tmp_path: Path) -> None:
    # The reviewer's toolset is (read_file, submit_verdict) — no directory listing. The kernel must hand
    # it the actual file manifest, or it guesses standard manifest names, never finds app.py/test_app.py,
    # and wrongly declares the worktree empty (the live-reviewer-blocks-clean-code bug).
    from chorus.heartbeat._scheduler import _worktree_file_manifest

    (tmp_path / "app.py").write_text("def slugify(s): return s\n")
    (tmp_path / "test_app.py").write_text("from app import slugify\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "util.py").write_text("x = 1\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / ".harness" / "roles").mkdir(parents=True)  # kernel-injected, not the author's work
    (tmp_path / ".harness" / "roles" / "reviewer.toml").write_text("x = 1\n")
    (tmp_path / ".dream").mkdir()
    (tmp_path / ".dream" / "registry.json").write_text("{}\n")

    manifest = _worktree_file_manifest(tmp_path)

    assert "app.py" in manifest
    assert "test_app.py" in manifest
    assert "pkg/util.py" in manifest
    assert ".git" not in manifest  # internal git plumbing is never review material
    assert ".harness" not in manifest  # kernel harness injection is identical in every worktree
    assert ".dream" not in manifest


def test_worktree_file_manifest_is_empty_for_no_worktree() -> None:
    from chorus.heartbeat._scheduler import _worktree_file_manifest

    assert _worktree_file_manifest(None) == ""
