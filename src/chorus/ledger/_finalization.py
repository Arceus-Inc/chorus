"""Independent GoalJudge — whether a ``done`` root is backed by durable evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from chorus.ledger._models import (
    Approval,
    ApprovalAction,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
    Artifact,
    ArtifactType,
    Dod,
    DodStatus,
    Run,
    RunStatus,
    Task,
    TaskStatus,
)
from chorus.outcomes import pr_landing_of

if TYPE_CHECKING:
    from chorus.ledger._ledger import Ledger


class FinalizationFailureReason(StrEnum):
    TASK_MISSING = "task_missing"
    TASK_NOT_DONE = "task_not_done"
    DOD_MISSING = "dod_missing"
    DOD_NOT_PASSED = "dod_not_passed"
    VERIFICATION_RUN_ID_MISSING = "verification_run_id_missing"
    VERIFICATION_RUN_MISSING = "verification_run_missing"
    VERIFICATION_RUN_TASK_MISMATCH = "verification_run_task_mismatch"
    VERIFICATION_RUN_NOT_SUCCEEDED = "verification_run_not_succeeded"
    PRIMARY_VERIFIED_ARTIFACT_MISSING = "primary_verified_artifact_missing"
    PRIMARY_UNMERGED = "primary_unmerged"


@dataclass(frozen=True)
class FinalizationInputs:
    task: Task | None
    dod: Dod | None
    verification_run: Run | None
    artifacts: tuple[Artifact, ...] = ()
    approvals: tuple[Approval, ...] = ()


@dataclass(frozen=True)
class FinalizationJudgment:
    passed: bool
    reason: FinalizationFailureReason | None = None

    def __post_init__(self) -> None:
        if self.passed and self.reason is not None:
            raise ValueError("passed finalization judgments cannot carry a failure reason")
        if not self.passed and self.reason is None:
            raise ValueError("failed finalization judgments require a failure reason")


class GoalJudge:
    """Read-only judge of completed goals from durable ledger evidence.

    The judge never writes. An unmerged PR or unverified primary deliverable is not success,
    even when a task row already says ``done``.
    """

    def judge(self, inputs: FinalizationInputs) -> FinalizationJudgment:
        task = inputs.task
        if task is None:
            return FinalizationJudgment(False, FinalizationFailureReason.TASK_MISSING)
        if task.status is not TaskStatus.DONE:
            return FinalizationJudgment(False, FinalizationFailureReason.TASK_NOT_DONE)

        latest = newest_primary_non_verdict(inputs.artifacts, task.id)
        if latest is not None and _is_unmerged(latest):
            return FinalizationJudgment(False, FinalizationFailureReason.PRIMARY_UNMERGED)

        if any(_is_approved_acceptance_gate(approval, task.id) for approval in inputs.approvals):
            if latest is not None and latest.review_state != "verified":
                return FinalizationJudgment(
                    False, FinalizationFailureReason.PRIMARY_VERIFIED_ARTIFACT_MISSING
                )
            return FinalizationJudgment(True)

        dod = inputs.dod
        if dod is None:
            return FinalizationJudgment(False, FinalizationFailureReason.DOD_MISSING)
        if dod.status is not DodStatus.PASSED:
            return FinalizationJudgment(False, FinalizationFailureReason.DOD_NOT_PASSED)
        if dod.verified_by_run_id is None:
            return FinalizationJudgment(False, FinalizationFailureReason.VERIFICATION_RUN_ID_MISSING)

        verification_run = inputs.verification_run
        if verification_run is None:
            return FinalizationJudgment(False, FinalizationFailureReason.VERIFICATION_RUN_MISSING)
        if verification_run.task_id != task.id:
            return FinalizationJudgment(
                False, FinalizationFailureReason.VERIFICATION_RUN_TASK_MISMATCH
            )
        if verification_run.status is not RunStatus.SUCCEEDED:
            return FinalizationJudgment(
                False, FinalizationFailureReason.VERIFICATION_RUN_NOT_SUCCEEDED
            )
        if latest is None or latest.review_state != "verified":
            return FinalizationJudgment(
                False, FinalizationFailureReason.PRIMARY_VERIFIED_ARTIFACT_MISSING
            )
        return FinalizationJudgment(True)

    def judge_task(self, ledger: Ledger, task_id: str) -> FinalizationJudgment:
        return self.judge(_inputs_for_task(ledger, task_id))


def judge_finalization(inputs: FinalizationInputs) -> FinalizationJudgment:
    return GoalJudge().judge(inputs)


def judge_task_finalization(ledger: Ledger, task_id: str) -> FinalizationJudgment:
    return GoalJudge().judge_task(ledger, task_id)


def _inputs_for_task(ledger: Ledger, task_id: str) -> FinalizationInputs:
    task = ledger.tasks.get(task_id)
    dod = ledger.dod.get_for_task(task_id)
    verification_run = None
    if dod is not None and dod.verified_by_run_id is not None:
        verification_run = ledger.runs.get(dod.verified_by_run_id)
    return FinalizationInputs(
        task=task,
        dod=dod,
        verification_run=verification_run,
        artifacts=tuple(ledger.artifacts.list_for_task(task_id)),
        approvals=tuple(ledger.approvals.for_subject(task_id)),
    )


def newest_primary_non_verdict(artifacts: Iterable[Artifact], task_id: str) -> Artifact | None:
    """The newest primary non-verdict for ``task_id`` — ``created_at DESC, id DESC``."""
    latest: Artifact | None = None
    for artifact in artifacts:
        if not _is_primary_non_verdict(artifact, task_id):
            continue
        if latest is None or _artifact_recency_key(artifact) > _artifact_recency_key(latest):
            latest = artifact
    return latest


def newest_pending_primary_non_verdict(
    artifacts: Iterable[Artifact], task_id: str
) -> Artifact | None:
    """The newest pending primary non-verdict for ``task_id`` — ``created_at DESC, id DESC``."""
    return newest_primary_non_verdict(
        (
            artifact
            for artifact in artifacts
            if artifact.review_state == "pending"
        ),
        task_id,
    )


def _artifact_recency_key(artifact: Artifact) -> tuple[datetime, str]:
    created = artifact.created_at
    if created is None:
        created = datetime.min.replace(tzinfo=UTC)
    elif created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (created, artifact.id)


def _is_primary_non_verdict(artifact: Artifact, task_id: str) -> bool:
    return (
        artifact.task_id == task_id
        and artifact.is_primary
        and artifact.type is not ArtifactType.VERDICT
    )


def _is_unmerged(artifact: Artifact) -> bool:
    return pr_landing_of(artifact.type.value, artifact.resource_ref).blocks_done


def _is_approved_acceptance_gate(approval: Approval, task_id: str) -> bool:
    return (
        approval.subject_kind is ApprovalSubjectKind.TASK
        and approval.subject_id == task_id
        and approval.action is ApprovalAction.TASK_GATE
        and approval.gate_kind is ApprovalGate.ACCEPTANCE
        and approval.status is ApprovalStatus.APPROVED
    )


__all__ = [
    "FinalizationFailureReason",
    "FinalizationInputs",
    "FinalizationJudgment",
    "GoalJudge",
    "judge_finalization",
    "judge_task_finalization",
    "newest_pending_primary_non_verdict",
    "newest_primary_non_verdict",
]
