"""Outcome landing — a passed beat records its role's artifact via the lander (spec 04 §2, spec 06 §2).

The kernel resolves the assignee role's ``outcome_kind``, calls the registered
:class:`~chorus.outcomes.OutcomeLander`, and records the returned artifact on the ledger before
finalising ``done``. With no landers wired it still finalises ``done`` (landing is additive).
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.outcomes import Artifact, ArtifactType, LanderRegistry, Verifier
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

    async def land(self, task: Any, result: Any) -> Artifact:
        self.landed.append(task.id)
        return Artifact(task_id=task.id, type=ArtifactType.PR, resource_ref={"branch": "chorus/e1"})


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
