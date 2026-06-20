"""PmLander — records a passed PM beat's plan doc as a durable ``doc`` artifact (spec 13 §4)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.outcomes import ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee import default_landers
from chorus_employee.pm import PM_PLAN_DOC, pm_lander, pm_plugin

pytestmark = pytest.mark.integration


def _task(assignee: str | None) -> Task:
    return Task(
        id="plan",
        intent="write the launch plan",
        status=TaskStatus.IN_PROGRESS,
        assignee_employee_id=assignee,
    )


def test_pm_lander_snapshots_the_plan_doc(tmp_path: Path) -> None:
    workspace = CompanyWorkspace(tmp_path / "acme")
    worktree = workspace.worktree_for("pat")
    (worktree.path / PM_PLAN_DOC).write_text("# Launch plan\n\nShip in Q3.\n", encoding="utf-8")

    artifact = asyncio.run(pm_lander(tmp_path / "acme").land(_task("pat"), None))

    assert artifact.type is ArtifactType.DOC and artifact.is_primary is True
    assert artifact.resource_ref["kind"] == "plan_doc"
    assert artifact.resource_ref["doc"] == PM_PLAN_DOC
    assert artifact.resource_ref["present"] is True
    assert artifact.resource_ref["branch"] == "chorus/pat"
    assert artifact.resource_ref["commit"]  # the snapshot sha


def test_pm_lander_records_a_missing_doc_as_absent(tmp_path: Path) -> None:
    workspace = CompanyWorkspace(tmp_path / "acme")
    workspace.worktree_for("pat")  # a worktree with no plan doc written

    artifact = asyncio.run(pm_lander(tmp_path / "acme").land(_task("pat"), None))

    assert artifact.type is ArtifactType.DOC
    assert artifact.resource_ref["present"] is False


def test_pm_lander_requires_an_assignee(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        asyncio.run(pm_lander(tmp_path / "acme").land(_task(None), None))


def test_pm_plugin_is_a_doc_writing_role() -> None:
    plugin = pm_plugin()
    assert plugin.name == "pm"
    assert plugin.outcome_kind == "doc"
    assert "write_file" in plugin.manifest.tools


def test_default_landers_registers_the_doc_lander(ledger: SqliteLedger, tmp_path: Path) -> None:
    registry = default_landers(tmp_path, ledger=ledger)
    assert registry.get("doc") is not None  # the kernel can land a PM beat
