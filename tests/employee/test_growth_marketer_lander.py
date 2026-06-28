"""GrowthMarketerLander — lands the action-class artifact (backtest / brief / launch) (spec GM §2)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.ledger import Task, TaskStatus
from chorus.outcomes import ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee.growth_marketer import growth_marketer_lander
from chorus_employee.growth_marketer._brief import (
    BACKTEST_REPORT_DOC,
    CAMPAIGN_BRIEF_DOC,
    EXPERIMENT_LAUNCH_DOC,
)

pytestmark = pytest.mark.integration


def _task(intent: str, assignee: str | None = "mira") -> Task:
    return Task(
        id="growth",
        intent=intent,
        status=TaskStatus.IN_PROGRESS,
        assignee_employee_id=assignee,
    )


def test_lands_a_backtest_report(tmp_path: Path) -> None:
    workspace = CompanyWorkspace(tmp_path / "acme")
    worktree = workspace.worktree_for("mira")
    (worktree.path / BACKTEST_REPORT_DOC).write_text("# Backtest\n\nVariant b wins, +1.4%.\n", encoding="utf-8")

    artifact = asyncio.run(
        growth_marketer_lander(tmp_path / "acme").land(_task("run a backtest of subject lines"), None)
    )

    assert artifact.type is ArtifactType.DOC
    assert artifact.resource_ref["kind"] == "backtest_report"
    assert artifact.resource_ref["doc"] == BACKTEST_REPORT_DOC
    assert artifact.resource_ref["present"] is True
    assert artifact.resource_ref["branch"] == "chorus/mira"
    assert artifact.resource_ref["commit"]


def test_lands_a_campaign_brief(tmp_path: Path) -> None:
    workspace = CompanyWorkspace(tmp_path / "acme")
    worktree = workspace.worktree_for("mira")
    (worktree.path / CAMPAIGN_BRIEF_DOC).write_text("# Brief\n\nTarget dormant cohort.\n", encoding="utf-8")

    artifact = asyncio.run(
        growth_marketer_lander(tmp_path / "acme").land(_task("draft a campaign brief"), None)
    )

    assert artifact.type is ArtifactType.DOC
    assert artifact.resource_ref["kind"] == "campaign_brief"
    assert artifact.resource_ref["present"] is True


def test_lands_an_experiment_launch_as_an_artifact(tmp_path: Path) -> None:
    workspace = CompanyWorkspace(tmp_path / "acme")
    worktree = workspace.worktree_for("mira")
    (worktree.path / EXPERIMENT_LAUNCH_DOC).write_text("# Launch\n\nLive to 40k.\n", encoding="utf-8")

    artifact = asyncio.run(
        growth_marketer_lander(tmp_path / "acme").land(
            _task("launch the live A/B test and send to 40k users"), None
        )
    )

    assert artifact.type is ArtifactType.ARTIFACT
    assert artifact.resource_ref["kind"] == "experiment_launched"
    assert artifact.resource_ref["present"] is True


def test_records_a_missing_deliverable_as_absent(tmp_path: Path) -> None:
    workspace = CompanyWorkspace(tmp_path / "acme")
    workspace.worktree_for("mira")  # no file written

    artifact = asyncio.run(
        growth_marketer_lander(tmp_path / "acme").land(_task("draft a campaign brief"), None)
    )
    assert artifact.resource_ref["present"] is False


def test_requires_an_assignee(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            growth_marketer_lander(tmp_path / "acme").land(_task("draft a brief", assignee=None), None)
        )
