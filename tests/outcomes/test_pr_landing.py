"""Typed PR landing disposition — done must not follow from an unmerged PR (BUG-005)."""

from __future__ import annotations

from chorus.outcomes import Artifact, ArtifactType, PrIntegration, pr_landing, pr_landing_of


def test_explicit_unmerged_pr_blocks_done() -> None:
    landing = pr_landing(
        Artifact(
            task_id="t1",
            type=ArtifactType.PR,
            resource_ref={"branch": "chorus/e1", "merged": False},
        )
    )
    assert landing.integration is PrIntegration.UNMERGED
    assert landing.blocks_done is True


def test_merged_pr_does_not_block_done() -> None:
    landing = pr_landing(
        Artifact(
            task_id="t1",
            type=ArtifactType.PR,
            resource_ref={"branch": "chorus/e1", "merged": True},
        )
    )
    assert landing.integration is PrIntegration.MERGED
    assert landing.blocks_done is False


def test_pr_without_merge_flag_does_not_block_done() -> None:
    landing = pr_landing(
        Artifact(task_id="t1", type=ArtifactType.PR, resource_ref={"branch": "chorus/e1"})
    )
    assert landing.integration is PrIntegration.NOT_RECORDED
    assert landing.blocks_done is False


def test_non_pr_artifact_does_not_block_done() -> None:
    landing = pr_landing(
        Artifact(task_id="t1", type=ArtifactType.DOC, resource_ref={"path": "spec.md"})
    )
    assert landing.integration is PrIntegration.NOT_RECORDED
    assert landing.blocks_done is False


def test_pr_landing_of_reads_persisted_type_value() -> None:
    landing = pr_landing_of("pr", {"merged": False})
    assert landing.blocks_done is True
    assert pr_landing_of("doc", {"merged": False}).blocks_done is False
