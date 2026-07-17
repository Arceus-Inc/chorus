"""AnalystLander — records a passed Analyst beat's findings doc as a ``finding`` artifact (spec 13 §4)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.ledger import Ledger, Task, TaskStatus
from chorus.outcomes import ArtifactType
from chorus.testing import uid
from chorus.workspace import CompanyWorkspace
from chorus_employee import default_landers
from chorus_employee.analyst import ANALYST_FINDINGS_DOC, analyst_lander, analyst_plugin

pytestmark = pytest.mark.integration


def _task(assignee: str | None) -> Task:
    return Task(
        id=uid("research"),
        intent="analyse the churn data",
        status=TaskStatus.IN_PROGRESS,
        assignee_employee_id=assignee,
    )


def test_analyst_lander_snapshots_the_findings_doc(tmp_path: Path) -> None:
    workspace = CompanyWorkspace(tmp_path / "acme")
    worktree = workspace.worktree_for("ana")
    (worktree.path / ANALYST_FINDINGS_DOC).write_text(
        "# Findings\n\nChurn rose 4% in May.\n", encoding="utf-8"
    )

    artifact = asyncio.run(analyst_lander(tmp_path / "acme").land(_task("ana"), None))

    assert artifact.type is ArtifactType.FINDING and artifact.is_primary is True
    assert artifact.resource_ref["kind"] == "findings_doc"
    assert artifact.resource_ref["doc"] == ANALYST_FINDINGS_DOC
    assert artifact.resource_ref["present"] is True
    assert artifact.resource_ref["branch"] == "chorus/ana"
    assert artifact.resource_ref["commit"]  # the snapshot sha


def test_analyst_lander_records_a_missing_doc_as_absent(tmp_path: Path) -> None:
    workspace = CompanyWorkspace(tmp_path / "acme")
    workspace.worktree_for("ana")  # a worktree with no findings doc written

    artifact = asyncio.run(analyst_lander(tmp_path / "acme").land(_task("ana"), None))

    assert artifact.type is ArtifactType.FINDING
    assert artifact.resource_ref["present"] is False


def test_analyst_lander_requires_an_assignee(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        asyncio.run(analyst_lander(tmp_path / "acme").land(_task(None), None))


def test_analyst_plugin_is_a_doc_writing_role() -> None:
    plugin = analyst_plugin()
    assert plugin.name == "analyst"
    assert plugin.outcome_kind == "finding"
    assert "write_file" in plugin.manifest.tools


def test_default_landers_registers_the_finding_lander(ledger: Ledger, tmp_path: Path) -> None:
    registry = default_landers(tmp_path, ledger=ledger)
    assert registry.get("finding") is not None  # the kernel can land an Analyst beat
