"""Outcome landing — a passed beat records its role's artifact via the lander (spec 04 §2, spec 06 §2).

The kernel resolves the assignee role's ``outcome_kind``, calls the registered
:class:`~chorus.outcomes.OutcomeLander`, and records the returned artifact on the ledger before
finalising ``done``. With no landers wired it still finalises ``done`` (landing is additive).
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from dream.contracts.strategy import LandedPhase, RecoveryHint

from chorus.events import EventKind
from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.outcomes import Artifact, ArtifactType, LanderRegistry, Verifier, pr_landing_of
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee
from chorus.workspace import CompanyWorkspace
from chorus_employee import default_landers

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-17T12:00:00+00:00")


class _PassingBeat:
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
        return BeatOutcome(passed=True, outcome={}, summary="ok")


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


class _RecordingLander:
    """An OutcomeLander stand-in that records the tasks it landed and returns a PR artifact."""

    outcome_kind = "pr"

    def __init__(self) -> None:
        self.landed: list[str] = []

    async def land(self, task: Task, result: BeatOutcome) -> Artifact:
        self.landed.append(task.id)
        return Artifact(task_id=task.id, type=ArtifactType.PR, resource_ref={"branch": "chorus/e1"})


class _ConflictingLander:
    """A PR lander whose branch never integrates — records an explicit unmerged PR."""

    outcome_kind = "pr"

    async def land(self, task: Task, result: BeatOutcome) -> Artifact:
        return Artifact(
            task_id=task.id,
            type=ArtifactType.PR,
            resource_ref={"branch": "chorus/e1", "into": "main", "merged": False},
        )


class _ConflictThenMergeLander:
    """First landing is an explicit unmerged PR; the rebase beat records a successful merge."""

    outcome_kind = "pr"

    def __init__(self) -> None:
        self.calls = 0

    async def land(self, task: Task, result: BeatOutcome) -> Artifact:
        self.calls += 1
        return Artifact(
            task_id=task.id,
            type=ArtifactType.PR,
            resource_ref={"branch": "chorus/e1", "into": "main", "merged": self.calls > 1},
        )


class _FailOnceThenPass:
    """One DoD failure, then passing beats — prior repair runs must not consume the merge cap."""

    def __init__(self) -> None:
        self.calls = 0

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
        self.calls += 1
        if self.calls == 1:
            return BeatOutcome(passed=False, outcome={}, summary="tests failed")
        return BeatOutcome(passed=True, outcome={}, summary="ok")


class _Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


def _seed(ledger: Ledger) -> Employee:
    employee = ledger.employees.create(Employee(id="e1", name="e1", role="backend_engineer"))
    ledger.tasks.submit(
        Task(id=uid("t1"), intent="ship", status=TaskStatus.TODO, assignee_employee_id="e1")
    )
    # An explicit objective DoD so the beat lands directly — these tests exercise the landing path, not
    # the backend engineer's reviewed-build gate (covered in test_m3_review.py).
    ledger.dod.create(uid("t1"), Verifier.command("true"))
    ledger.wakes.enqueue(
        Wake(
            id=uid("w1"),
            employee_id="e1",
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": uid("t1")},
        )
    )
    return employee


async def _run(ledger: Ledger, *, landers: LanderRegistry | None) -> None:
    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(_seed(ledger)),
        beat_runner=_PassingBeat(),
        roles=RoleRegistry.from_plugins(default_roles()),
        landers=landers,
        max_concurrent_runs=1,
    )
    await sched.tick(_NOW)
    await sched.drain()


async def test_passed_beat_records_the_role_artifact(ledger: Ledger) -> None:
    lander = _RecordingLander()
    await _run(ledger, landers=LanderRegistry.from_landers([lander]))

    assert lander.landed == [uid("t1")]
    artifacts = ledger.artifacts.list_for_task(uid("t1"))
    assert len(artifacts) == 1 and artifacts[0].type.value == "pr"  # recorded on the ledger
    assert artifacts[0].resource_ref == {"branch": "chorus/e1"}
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.DONE  # type: ignore[union-attr]


async def test_no_lander_still_finalises_done(ledger: Ledger) -> None:
    await _run(ledger, landers=None)  # back-compat: nothing to land

    assert ledger.artifacts.list_for_task(uid("t1")) == []
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.DONE  # type: ignore[union-attr]


async def test_unmerged_branch_redispatches_the_author_instead_of_going_done(
    ledger: Ledger,
) -> None:
    """BUG-005, rung 1: a passed beat whose PR did not merge must not finalise ``done``."""
    recorder = _Recorder()
    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(_seed(ledger)),
        beat_runner=_PassingBeat(),
        roles=RoleRegistry.from_plugins(default_roles()),
        landers=LanderRegistry.from_landers([_ConflictingLander()]),
        max_concurrent_runs=1,
        event_bus=recorder,
    )
    await sched.tick(_NOW)
    await sched.drain()

    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.TODO
    artifacts = ledger.artifacts.list_for_task(uid("t1"))
    assert len(artifacts) == 1
    assert artifacts[0].review_state != "verified"
    redispatch = [
        wake for wake in ledger.wakes.queued() if wake.payload.get("cause") == "merge_conflict"
    ]
    assert len(redispatch) == 1 and redispatch[0].employee_id == "e1"
    carryover = ledger.run_carryovers.for_task(uid("t1"))[-1]
    assert carryover.phase is LandedPhase.NEEDS_REWORK
    assert carryover.recovery_hint is RecoveryHint.REWORK
    landed = [event for event in recorder.events if event.kind is EventKind.OUTCOME_LANDED]
    assert len(landed) == 1
    assert landed[0].payload["phase"] == LandedPhase.NEEDS_REWORK.value
    assert landed[0].payload["passed"] is False


async def test_unmerged_branch_blocks_with_a_recovery_card_after_the_cap(
    ledger: Ledger,
) -> None:
    """BUG-005, rung 2: exhausted rebase attempts block with a recovery card — never silently done."""
    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(_seed(ledger)),
        beat_runner=_PassingBeat(),
        roles=RoleRegistry.from_plugins(default_roles()),
        landers=LanderRegistry.from_landers([_ConflictingLander()]),
        max_concurrent_runs=1,
        max_repair_attempts=0,
    )
    await sched.tick(_NOW)
    await sched.drain()

    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.BLOCKED
    card = ledger.recovery_actions.active_for_source(uid("t1"))
    assert card is not None and "merge_conflict" in card.cause
    carryover = ledger.run_carryovers.for_task(uid("t1"))[-1]
    assert carryover.phase is LandedPhase.STRANDED
    assert carryover.recovery_hint is RecoveryHint.ESCALATE


async def test_merge_repair_cap_ignores_prior_dod_failure(ledger: Ledger) -> None:
    """Default cap counts unmerged-PR landings only — a prior DoD failure does not exhaust it."""
    beat = _FailOnceThenPass()
    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(_seed(ledger)),
        beat_runner=beat,
        roles=RoleRegistry.from_plugins(default_roles()),
        landers=LanderRegistry.from_landers([_ConflictingLander()]),
        max_concurrent_runs=1,
    )

    await sched.tick(_NOW)
    await sched.drain()
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.TODO  # type: ignore[union-attr]

    await sched.tick(_NOW)
    await sched.drain()
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.TODO  # type: ignore[union-attr]
    assert ledger.recovery_actions.active_for_source(uid("t1")) is None

    await sched.tick(_NOW)
    await sched.drain()
    # Second unmerged landing is still within the default cap of 2, even though this is the
    # third author run (DoD failure + two merge conflicts).
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.TODO  # type: ignore[union-attr]

    await sched.tick(_NOW)
    await sched.drain()
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.BLOCKED
    assert beat.calls == 4
    unmerged = [
        artifact
        for artifact in ledger.artifacts.list_for_task(uid("t1"))
        if pr_landing_of(artifact.type.value, artifact.resource_ref).blocks_done
    ]
    assert len(unmerged) == 3
    assert all(artifact.review_state != "verified" for artifact in unmerged)


async def test_unmerged_then_successful_merge_is_terminal_pass(
    ledger: Ledger,
) -> None:
    """OUTCOME_LANDED uses this beat's landing — a prior unmerged PR must not poison a later merge."""
    recorder = _Recorder()
    lander = _ConflictThenMergeLander()
    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(_seed(ledger)),
        beat_runner=_PassingBeat(),
        roles=RoleRegistry.from_plugins(default_roles()),
        landers=LanderRegistry.from_landers([lander]),
        max_concurrent_runs=1,
        event_bus=recorder,
    )

    await sched.tick(_NOW)
    await sched.drain()
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.TODO  # type: ignore[union-attr]
    first = ledger.artifacts.list_for_task(uid("t1"))[-1]
    assert first.review_state != "verified"
    assert pr_landing_of(first.type.value, first.resource_ref).blocks_done is True

    await sched.tick(_NOW)
    await sched.drain()
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.DONE
    artifacts = ledger.artifacts.list_for_task(uid("t1"))
    assert len(artifacts) == 2
    latest = artifacts[-1]
    assert latest.review_state == "verified"
    assert pr_landing_of(latest.type.value, latest.resource_ref).blocks_done is False
    carryover = ledger.run_carryovers.for_task(uid("t1"))[-1]
    assert carryover.phase is LandedPhase.TERMINAL_PASS
    landed = [event for event in recorder.events if event.kind is EventKind.OUTCOME_LANDED]
    assert len(landed) == 2
    assert landed[0].payload["phase"] == LandedPhase.NEEDS_REWORK.value
    assert landed[1].payload["phase"] == LandedPhase.TERMINAL_PASS.value
    assert landed[1].payload["passed"] is True


async def test_real_engineer_lander_records_a_pr_with_a_real_commit(
    ledger: Ledger, tmp_path: Path
) -> None:
    # the real engineering lander over a real worktree: full kernel landing, no fakes
    company_root = tmp_path / "acme"
    worktree = CompanyWorkspace(company_root).worktree_for("e1").path
    (worktree / "feature.py").write_text("def f():\n    return 1\n", encoding="utf-8")  # the work

    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(_seed(ledger)),
        beat_runner=_PassingBeat(),
        roles=RoleRegistry.from_plugins(default_roles()),
        landers=default_landers(company_root),
        max_concurrent_runs=1,
    )
    await sched.tick(_NOW)
    await sched.drain()

    artifacts = ledger.artifacts.list_for_task(uid("t1"))
    assert len(artifacts) == 1
    pr = artifacts[0]
    assert pr.type.value == "pr"
    assert pr.resource_ref is not None
    assert pr.resource_ref["branch"] == "chorus/e1"
    assert pr.resource_ref["commit"]  # a real commit sha
    # the employee's work was committed on its branch (the "PR" has content)
    tracked = subprocess.run(
        ["git", "-C", str(worktree), "ls-files"], check=True, capture_output=True, text=True
    ).stdout
    assert "feature.py" in tracked
