from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

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
    GoalJudge,
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
    review_state: str | None = "verified",
    resource_ref: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> Artifact:
    return Artifact(
        id=artifact_id,
        task_id=task_id,
        type=artifact_type,
        review_state=review_state,
        is_primary=True,
        resource_ref=resource_ref,
        created_at=created_at,
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


def test_unmerged_pr_is_not_success_even_when_stamped_verified() -> None:
    judgment = GoalJudge().judge(
        FinalizationInputs(
            task=_task(),
            dod=_dod(),
            verification_run=_run(),
            artifacts=(
                _artifact(resource_ref={"branch": "chorus/e1", "merged": False}),
            ),
        )
    )

    assert judgment.passed is False
    assert judgment.reason is FinalizationFailureReason.PRIMARY_UNMERGED


def test_approved_acceptance_does_not_treat_unverified_artifact_as_success() -> None:
    judgment = GoalJudge().judge(
        FinalizationInputs(
            task=_task(),
            dod=None,
            verification_run=None,
            artifacts=(_artifact(review_state="pending"),),
            approvals=(_acceptance_approval(),),
        )
    )

    assert judgment.passed is False
    assert judgment.reason is FinalizationFailureReason.PRIMARY_VERIFIED_ARTIFACT_MISSING


def test_approved_acceptance_does_not_treat_unmerged_pr_as_success() -> None:
    judgment = GoalJudge().judge(
        FinalizationInputs(
            task=_task(),
            dod=None,
            verification_run=None,
            artifacts=(
                _artifact(
                    review_state="verified",
                    resource_ref={"branch": "chorus/e1", "merged": False},
                ),
            ),
            approvals=(_acceptance_approval(),),
        )
    )

    assert judgment.passed is False
    assert judgment.reason is FinalizationFailureReason.PRIMARY_UNMERGED


def test_goal_judge_is_read_only_and_does_not_rewrite_inputs() -> None:
    artifact = _artifact(resource_ref={"branch": "chorus/e1", "merged": True})
    inputs = FinalizationInputs(
        task=_task(),
        dod=_dod(),
        verification_run=_run(),
        artifacts=(artifact,),
    )

    first = GoalJudge().judge(inputs)
    second = GoalJudge().judge(inputs)

    assert first == second
    assert first.passed is True
    assert inputs.artifacts[0] is artifact
    assert inputs.artifacts[0].review_state == "verified"
    assert inputs.artifacts[0].resource_ref == {"branch": "chorus/e1", "merged": True}
    assert replace(artifact, review_state="pending").review_state == "pending"
    assert artifact.review_state == "verified"


def test_goal_judge_uses_created_at_desc_id_desc_not_tuple_order() -> None:
    older = _artifact(
        artifact_id="zzz-old",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        resource_ref={"branch": "chorus/e1", "merged": True},
    )
    newer = _artifact(
        artifact_id="aaa-new",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        review_state="pending",
    )
    judgment = GoalJudge().judge(
        FinalizationInputs(
            task=_task(),
            dod=_dod(),
            verification_run=_run(),
            artifacts=(newer, older),
        )
    )

    assert judgment.passed is False
    assert judgment.reason is FinalizationFailureReason.PRIMARY_VERIFIED_ARTIFACT_MISSING


def test_goal_judge_breaks_created_at_ties_by_id_desc() -> None:
    stamp = datetime(2026, 8, 1, tzinfo=UTC)
    lower_id = _artifact(artifact_id="aaa", created_at=stamp, review_state="pending")
    higher_id = _artifact(
        artifact_id="zzz",
        created_at=stamp,
        resource_ref={"branch": "chorus/e1", "merged": True},
    )
    judgment = GoalJudge().judge(
        FinalizationInputs(
            task=_task(),
            dod=_dod(),
            verification_run=_run(),
            artifacts=(higher_id, lower_id),
        )
    )

    assert judgment.passed is True
    assert judgment.reason is None
