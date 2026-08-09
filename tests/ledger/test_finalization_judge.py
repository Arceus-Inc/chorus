from __future__ import annotations

import pytest

from chorus.ledger import (
    Approval,
    ApprovalAction,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
    Artifact,
    ArtifactType,
    Dod,
    DodStatus,
    ExecutionMode,
    Run,
    RunStatus,
    Task,
    TaskStatus,
)
from chorus.ledger._finalization import (
    FinalizationFailureReason,
    FinalizationInputs,
    judge_finalization,
)


def _task(
    *,
    task_id: str = "root",
    status: TaskStatus = TaskStatus.DONE,
    execution_mode: ExecutionMode = ExecutionMode.DELIVERY,
) -> Task:
    return Task(
        id=task_id,
        intent="ship it",
        status=status,
        assignee_employee_id="e1",
        execution_mode=execution_mode,
    )


def _dod(
    *,
    task_id: str = "root",
    status: DodStatus = DodStatus.PASSED,
    verified_by_run_id: str | None = "run-root",
) -> Dod:
    return Dod(
        id=f"dod-{task_id}",
        task_id=task_id,
        kind="command",
        status=status,
        verified_by_run_id=verified_by_run_id,
    )


def _run(
    *,
    run_id: str = "run-root",
    task_id: str = "root",
    status: RunStatus = RunStatus.SUCCEEDED,
) -> Run:
    return Run(id=run_id, employee_id="e1", task_id=task_id, status=status)


def _artifact(
    *,
    artifact_id: str = "art-root",
    task_id: str = "root",
    artifact_type: ArtifactType = ArtifactType.PR,
) -> Artifact:
    return Artifact(
        id=artifact_id,
        task_id=task_id,
        type=artifact_type,
        review_state="verified",
        is_primary=True,
    )


def _acceptance_approval(
    *,
    status: ApprovalStatus = ApprovalStatus.APPROVED,
    gate_kind: ApprovalGate = ApprovalGate.ACCEPTANCE,
) -> Approval:
    return Approval(
        id="approval-root",
        subject_kind=ApprovalSubjectKind.TASK,
        subject_id="root",
        reason="human finalization",
        action=ApprovalAction.TASK_GATE,
        status=status,
        gate_kind=gate_kind,
    )


def test_leaf_done_task_passes_with_succeeded_verifier_and_verified_primary_artifact() -> None:
    judgment = judge_finalization(
        FinalizationInputs(
            task=_task(),
            dod=_dod(),
            verification_run=_run(),
            artifacts=(_artifact(),),
        )
    )

    assert judgment.passed is True
    assert judgment.reason is None


def test_approved_acceptance_gate_is_valid_human_finalization_evidence() -> None:
    judgment = judge_finalization(
        FinalizationInputs(
            task=_task(),
            dod=None,
            verification_run=None,
            approvals=(_acceptance_approval(),),
        )
    )

    assert judgment.passed is True
    assert judgment.reason is None


@pytest.mark.parametrize(
    "approval",
    (
        _acceptance_approval(status=ApprovalStatus.DENIED),
        _acceptance_approval(status=ApprovalStatus.REVISION_REQUESTED),
        _acceptance_approval(gate_kind=ApprovalGate.AUTHORIZATION),
    ),
)
def test_only_approved_acceptance_gates_are_human_finalization_evidence(
    approval: Approval,
) -> None:
    judgment = judge_finalization(
        FinalizationInputs(task=_task(), dod=None, verification_run=None, approvals=(approval,))
    )

    assert judgment.passed is False
    assert judgment.reason is FinalizationFailureReason.DOD_MISSING


def test_done_task_without_verified_primary_artifact_fails() -> None:
    judgment = judge_finalization(
        FinalizationInputs(task=_task(), dod=_dod(), verification_run=_run())
    )

    assert judgment.passed is False
    assert judgment.reason is FinalizationFailureReason.PRIMARY_VERIFIED_ARTIFACT_MISSING


def test_verdict_artifact_does_not_count_as_final_artifact() -> None:
    judgment = judge_finalization(
        FinalizationInputs(
            task=_task(),
            dod=_dod(),
            verification_run=_run(),
            artifacts=(_artifact(artifact_type=ArtifactType.VERDICT),),
        )
    )

    assert judgment.passed is False
    assert judgment.reason is FinalizationFailureReason.PRIMARY_VERIFIED_ARTIFACT_MISSING


def test_done_task_fails_when_verified_run_belongs_to_another_task() -> None:
    judgment = judge_finalization(
        FinalizationInputs(
            task=_task(),
            dod=_dod(),
            verification_run=_run(task_id="other"),
            artifacts=(_artifact(),),
        )
    )

    assert judgment.passed is False
    assert judgment.reason is FinalizationFailureReason.VERIFICATION_RUN_TASK_MISMATCH


def test_delegated_root_subtree_artifact_does_not_count() -> None:
    judgment = judge_finalization(
        FinalizationInputs(
            task=_task(execution_mode=ExecutionMode.DELEGATION),
            dod=_dod(),
            verification_run=_run(),
            artifacts=(_artifact(task_id="child", artifact_id="art-child"),),
        )
    )

    assert judgment.passed is False
    assert judgment.reason is FinalizationFailureReason.PRIMARY_VERIFIED_ARTIFACT_MISSING


def test_delegated_root_passes_when_it_has_its_own_verified_primary_artifact() -> None:
    judgment = judge_finalization(
        FinalizationInputs(
            task=_task(execution_mode=ExecutionMode.DELEGATION),
            dod=_dod(),
            verification_run=_run(),
            artifacts=(
                _artifact(task_id="child", artifact_id="art-child"),
                _artifact(task_id="root", artifact_id="art-root"),
            ),
        )
    )

    assert judgment.passed is True
    assert judgment.reason is None
