"""EngineerLander — a passed engineer beat lands a PR artifact (spec 04 §2, spec 06 §2).

"Done" for an engineer is "PR opened, CI green": the CI gate is the Command DoD (enforced elsewhere);
the PR is the engineer's branch + its committed work, captured as a ``pr`` artifact. The lander
snapshots the worktree and returns the canonical :class:`~chorus.outcomes.Artifact`; the kernel records it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chorus.ledger import Task
from chorus.outcomes import ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee.engineer import engineer_lander

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


async def test_land_snapshots_the_worktree_and_returns_a_pr_artifact(tmp_path: Path) -> None:
    company_root = tmp_path / "acme"
    workspace = CompanyWorkspace(company_root)
    wt = workspace.worktree_for("ada")
    (wt.path / "feature.py").write_text("print('shipped')\n", encoding="utf-8")  # uncommitted work

    lander = engineer_lander(company_root)
    assert lander.outcome_kind == "pr"
    artifact = await lander.land(
        Task(id="t1", intent="ship it", assignee_employee_id="ada"), result=None
    )

    assert artifact.task_id == "t1"
    assert artifact.type is ArtifactType.PR
    assert artifact.resource_ref["branch"] == "chorus/ada"
    assert artifact.resource_ref["commit"]  # a real commit sha
    # the engineer's work is now committed on its branch (the "PR" has content)
    assert "feature.py" in _git(wt.path, "ls-files")
    assert artifact.resource_ref["commit"] == _git(wt.path, "rev-parse", "HEAD")
