from __future__ import annotations

from dataclasses import replace

import pytest

from chorus.governance._actions._task_gate import TaskGateAction, TaskGateError
from chorus.ledger import (
    Approval,
    ApprovalAction,
    ApprovalGate,
    ApprovalSubjectKind,
    Artifact,
    ArtifactType,
    Dod,
    DodStatus,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    judge_task_finalization,
)


class _FakeTasks:
    def __init__(self, task: Task) -> None:
        self._task = task

    def get(self, task_id: str) -> Task | None:
        return self._task if self._task.id == task_id else None


class _FakeDodRepo:
    def __init__(self, dod: Dod) -> None:
        self._dod = dod

    def get_for_task(self, task_id: str) -> Dod | None:
        return self._dod if self._dod.task_id == task_id else None


class _FakeRuns:
    def __init__(self, runs: list[Run]) -> None:
        self._runs = runs

    def for_task(self, task_id: str) -> list[Run]:
        return [run for run in self._runs if run.task_id == task_id]

    def get(self, run_id: str) -> Run | None:
        for run in self._runs:
            if run.id == run_id:
                return run
        return None


class _FakeArtifacts:
    def __init__(self, artifacts: list[Artifact]) -> None:
        self._artifacts = artifacts

    def has_pending_primary_non_verdict(self, task_id: str) -> bool:
        return any(
            artifact.task_id == task_id
            and artifact.is_primary
            and artifact.type is not ArtifactType.VERDICT
            and artifact.review_state == "pending"
            for artifact in self._artifacts
        )

    def mark_latest_pending_primary_non_verdict_verified(self, task_id: str) -> Artifact | None:
        for index in range(len(self._artifacts) - 1, -1, -1):
            artifact = self._artifacts[index]
            if artifact.task_id != task_id or not artifact.is_primary:
                continue
            if artifact.type is ArtifactType.VERDICT:
                continue
            if artifact.review_state != "pending":
                continue
            updated = replace(artifact, review_state="verified")
            self._artifacts[index] = updated
            return updated
        return None

    def list_for_task(self, task_id: str) -> list[Artifact]:
        return [artifact for artifact in self._artifacts if artifact.task_id == task_id]


class _FakeApprovals:
    def for_subject(self, task_id: str) -> list[Approval]:
        del task_id
        return []


class _FakeLedger:
    def __init__(self, task: Task, dod: Dod, runs: list[Run], artifacts: list[Artifact]) -> None:
        self.tasks = _FakeTasks(task)
        self.dod = _FakeDodRepo(dod)
        self.runs = _FakeRuns(runs)
        self.artifacts = _FakeArtifacts(artifacts)
        self.approvals = _FakeApprovals()
        self.finalize_calls: list[tuple[str, str | None, DodStatus]] = []
        self._task = task
        self._dod = dod

    def finalize_beat(
        self,
        *,
        task_id: str,
        run_id: str | None,
        dod_status: DodStatus,
        verdict: dict[str, object] | None = None,
    ) -> list[object]:
        del verdict
        self.finalize_calls.append((task_id, run_id, dod_status))
        self._task = replace(self._task, status=TaskStatus.DONE)
        self.tasks = _FakeTasks(self._task)
        self._dod = replace(self._dod, status=dod_status, verified_by_run_id=run_id)
        self.dod = _FakeDodRepo(self._dod)
        return []


def _approval(task_id: str = "task-1") -> Approval:
    return Approval(
        id="approval-1",
        subject_kind=ApprovalSubjectKind.TASK,
        subject_id=task_id,
        reason="sign off",
        action=ApprovalAction.TASK_GATE,
        gate_kind=ApprovalGate.ACCEPTANCE,
    )


def test_acceptance_approval_verifies_artifact_and_passes_goal_judge() -> None:
    ledger = _FakeLedger(
        task=Task(id="task-1", intent="ship", status=TaskStatus.BLOCKED, assignee_employee_id="e1"),
        dod=Dod(
            id="dod-1",
            task_id="task-1",
            kind="human_approval",
            status=DodStatus.PENDING,
        ),
        runs=[
            Run(id="run-old", employee_id="e1", task_id="task-1", status=RunStatus.FAILED),
            Run(id="run-new", employee_id="e1", task_id="task-1", status=RunStatus.SUCCEEDED),
        ],
        artifacts=[
            Artifact(
                id="artifact-1",
                task_id="task-1",
                type=ArtifactType.DOC,
                is_primary=True,
                review_state="pending",
            )
        ],
    )

    outcome = TaskGateAction(ledger).on_approve(_approval())

    assert outcome.subject_status == TaskStatus.DONE.value
    assert ledger.finalize_calls == [("task-1", "run-new", DodStatus.PASSED)]
    judgment = judge_task_finalization(ledger, "task-1")
    assert judgment.passed is True
    assert judgment.reason is None


def test_acceptance_approval_fails_closed_without_producer_run() -> None:
    ledger = _FakeLedger(
        task=Task(id="task-1", intent="ship", status=TaskStatus.BLOCKED, assignee_employee_id="e1"),
        dod=Dod(id="dod-1", task_id="task-1", kind="human_approval", status=DodStatus.PENDING),
        runs=[],
        artifacts=[
            Artifact(
                id="artifact-1",
                task_id="task-1",
                type=ArtifactType.DOC,
                is_primary=True,
                review_state="pending",
            )
        ],
    )

    with pytest.raises(TaskGateError, match="succeeded producer run"):
        TaskGateAction(ledger).on_approve(_approval())
    assert ledger.finalize_calls == []
    assert ledger.artifacts.list_for_task("task-1")[0].review_state == "pending"


def test_acceptance_approval_fails_closed_without_primary_non_verdict_artifact() -> None:
    ledger = _FakeLedger(
        task=Task(id="task-1", intent="ship", status=TaskStatus.BLOCKED, assignee_employee_id="e1"),
        dod=Dod(id="dod-1", task_id="task-1", kind="human_approval", status=DodStatus.PENDING),
        runs=[Run(id="run-1", employee_id="e1", task_id="task-1", status=RunStatus.SUCCEEDED)],
        artifacts=[],
    )

    with pytest.raises(TaskGateError, match="primary non-verdict artifact"):
        TaskGateAction(ledger).on_approve(_approval())
    assert ledger.finalize_calls == []


def test_generic_acceptance_gate_keeps_legacy_done_without_strict_evidence() -> None:
    ledger = _FakeLedger(
        task=Task(id="task-1", intent="ship", status=TaskStatus.BLOCKED, assignee_employee_id="e1"),
        dod=Dod(id="dod-1", task_id="task-1", kind="command", status=DodStatus.PENDING),
        runs=[],
        artifacts=[],
    )

    outcome = TaskGateAction(ledger).on_approve(_approval())

    assert outcome.subject_status == TaskStatus.DONE.value
    assert ledger.finalize_calls == [("task-1", None, DodStatus.PASSED)]
