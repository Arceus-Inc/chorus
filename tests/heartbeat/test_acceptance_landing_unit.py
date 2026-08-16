from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace

from chorus.governance import GovernanceResolver
from chorus.heartbeat import Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import (
    Approval,
    ApprovalAction,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
)
from chorus.ledger._models import Artifact, ArtifactType, Task, TaskStatus
from chorus.outcomes import Artifact as OutcomeArtifact
from chorus.outcomes import ArtifactType as OutcomeArtifactType
from chorus.outcomes import LanderRegistry, Verifier
from chorus.workforce import Employee


class _FakePendingApprovals:
    def __init__(self, approvals: list[Approval]) -> None:
        self._approvals = approvals

    def pending(self) -> list[Approval]:
        return list(self._approvals)


class _FakeArtifacts:
    def __init__(self) -> None:
        self.created: list[Artifact] = []

    def create(self, artifact: Artifact) -> Artifact:
        self.created.append(artifact)
        return artifact

    def list_for_task(self, task_id: str) -> list[Artifact]:
        return [artifact for artifact in self.created if artifact.task_id == task_id]


class _FakeTasks:
    def __init__(self, task: Task) -> None:
        self.task = task
        self.transitions: list[TaskStatus] = []

    def get(self, task_id: str) -> Task | None:
        return self.task if self.task.id == task_id else None

    def transition(self, task_id: str, status: TaskStatus) -> None:
        if task_id != self.task.id:
            return
        self.transitions.append(status)
        self.task = replace(self.task, status=status)


class _FakeLedger:
    def __init__(self, approvals: list[Approval]) -> None:
        self.tasks = _FakeTasks(
            Task(id="task-1", intent="ship", status=TaskStatus.IN_PROGRESS, assignee_employee_id="e1")
        )
        self.approvals = _FakePendingApprovals(approvals)
        self.artifacts = _FakeArtifacts()

    def transaction(self):
        return nullcontext()

    def record_integration_verdict(self, task_id: str, integration: object) -> None:
        del task_id, integration


class _FakeLander:
    outcome_kind = "doc"

    async def land(self, task: Task, result: BeatOutcome) -> OutcomeArtifact:
        del result
        return OutcomeArtifact(task_id=task.id, type=OutcomeArtifactType.DOC)


class _UnmergedLander:
    outcome_kind = "pr"

    async def land(self, task: Task, result: BeatOutcome) -> OutcomeArtifact:
        del result
        return OutcomeArtifact(
            task_id=task.id,
            type=OutcomeArtifactType.PR,
            resource_ref={"branch": "chorus/e1", "merged": False},
        )


def _approval(gate_kind: ApprovalGate) -> Approval:
    return Approval(
        id="approval-1",
        subject_kind=ApprovalSubjectKind.TASK,
        subject_id="task-1",
        reason="sign off",
        action=ApprovalAction.TASK_GATE,
        status=ApprovalStatus.PENDING,
        gate_kind=gate_kind,
    )


async def test_pending_acceptance_gate_lands_pending_artifact_before_blocking() -> None:
    ledger = _FakeLedger([_approval(ApprovalGate.ACCEPTANCE)])
    scheduler = Scheduler(ledger=ledger, landers=LanderRegistry.from_landers([_FakeLander()]))

    await scheduler._land_passed(
        "task-1",
        run_id="run-1",
        verifier=None,
        verdict={},
        employee=Employee(id="e1", name="E1", role="engineer"),
        result=BeatOutcome(passed=True, outcome={}, summary="ok"),
        outcome_kind="doc",
    )

    assert ledger.tasks.task.status is TaskStatus.BLOCKED
    assert ledger.tasks.transitions == [TaskStatus.BLOCKED]
    assert len(ledger.artifacts.created) == 1
    assert ledger.artifacts.created[0].review_state == "pending"
    assert ledger.artifacts.created[0].type is ArtifactType.DOC


async def test_pending_authorization_gate_blocks_without_landing_an_artifact() -> None:
    ledger = _FakeLedger([_approval(ApprovalGate.AUTHORIZATION)])
    scheduler = Scheduler(ledger=ledger, landers=LanderRegistry.from_landers([_FakeLander()]))

    await scheduler._land_passed(
        "task-1",
        run_id="run-1",
        verifier=None,
        verdict={},
        employee=Employee(id="e1", name="E1", role="engineer"),
        result=BeatOutcome(passed=True, outcome={}, summary="ok"),
        outcome_kind="doc",
    )

    assert ledger.tasks.task.status is TaskStatus.BLOCKED
    assert ledger.artifacts.created == []


async def test_human_approval_dod_lands_pending_artifact_before_opening_gate(
    monkeypatch,
) -> None:
    ledger = _FakeLedger([])
    scheduler = Scheduler(ledger=ledger, landers=LanderRegistry.from_landers([_FakeLander()]))
    opened: list[tuple[str, ApprovalGate, str]] = []

    def _open_task_gate(
        self, task_id: str, *, gate_kind: ApprovalGate, reason: str
    ) -> None:
        opened.append((task_id, gate_kind, reason))

    monkeypatch.setattr(GovernanceResolver, "open_task_gate", _open_task_gate)

    await scheduler._land_passed(
        "task-1",
        run_id="run-1",
        verifier=Verifier.human_approval(),
        verdict={},
        employee=Employee(id="e1", name="E1", role="engineer"),
        result=BeatOutcome(passed=True, outcome={}, summary="ok"),
        outcome_kind="doc",
    )

    assert len(ledger.artifacts.created) == 1
    assert ledger.artifacts.created[0].review_state == "pending"
    assert opened == [("task-1", ApprovalGate.ACCEPTANCE, "human-approval DoD for task-1")]


async def test_strict_acceptance_revision_loop_lands_a_fresh_pending_artifact_each_attempt() -> None:
    ledger = _FakeLedger([])
    scheduler = Scheduler(ledger=ledger, landers=LanderRegistry.from_landers([_FakeLander()]))
    employee = Employee(id="e1", name="E1", role="engineer")
    result = BeatOutcome(passed=True, outcome={}, summary="ok")

    await scheduler._land_pending_acceptance_artifact(
        "task-1", employee=employee, result=result, outcome_kind="doc"
    )
    await scheduler._land_pending_acceptance_artifact(
        "task-1", employee=employee, result=result, outcome_kind="doc"
    )

    assert len(ledger.artifacts.created) == 2
    assert [artifact.review_state for artifact in ledger.artifacts.created] == ["pending", "pending"]


async def test_pending_acceptance_does_not_stamp_an_unmerged_pr_verified() -> None:
    ledger = _FakeLedger([_approval(ApprovalGate.ACCEPTANCE)])
    scheduler = Scheduler(ledger=ledger, landers=LanderRegistry.from_landers([_UnmergedLander()]))

    await scheduler._land_passed(
        "task-1",
        run_id="run-1",
        verifier=None,
        verdict={},
        employee=Employee(id="e1", name="E1", role="engineer"),
        result=BeatOutcome(passed=True, outcome={}, summary="ok"),
        outcome_kind="pr",
    )

    assert ledger.tasks.task.status is TaskStatus.BLOCKED
    assert len(ledger.artifacts.created) == 1
    assert ledger.artifacts.created[0].review_state != "verified"
    assert ledger.artifacts.created[0].type is ArtifactType.PR
    assert ledger.artifacts.created[0].resource_ref == {"branch": "chorus/e1", "merged": False}
