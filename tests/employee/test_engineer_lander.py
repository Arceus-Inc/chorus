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
from chorus.testing import uid
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
        Task(id=uid("t1"), intent="ship it", assignee_employee_id="ada"), result=None
    )

    assert artifact.task_id == uid("t1")
    assert artifact.type is ArtifactType.PR
    assert artifact.resource_ref["branch"] == "chorus/ada"
    assert artifact.resource_ref["commit"]  # a real commit sha
    # the engineer's work is now committed on its branch (the "PR" has content)
    assert "feature.py" in _git(wt.path, "ls-files")
    assert artifact.resource_ref["commit"] == _git(wt.path, "rev-parse", "HEAD")


async def test_land_integrates_the_branch_into_company_main(tmp_path: Path) -> None:
    # an Engineer's outcome is "PR → CI → merge": once CI (the DoD) is green the lander integrates the
    # branch into the company ``main`` so the next employee branches off the shipped work.
    company_root = tmp_path / "acme"
    workspace = CompanyWorkspace(company_root)
    wt = workspace.worktree_for("ada")
    (wt.path / "feature.py").write_text("print('shipped')\n", encoding="utf-8")

    artifact = await engineer_lander(company_root).land(
        Task(id=uid("t1"), intent="ship it", assignee_employee_id="ada"), result=None
    )

    assert artifact.resource_ref["merged"] is True
    assert artifact.resource_ref["into"] == "main"
    # the company ``main`` now carries the engineer's deliverable
    assert "feature.py" in _git(workspace.repo, "ls-files")


async def test_artifact_ref_is_host_safe(tmp_path: Path) -> None:
    # spec 04 §2: a workspace reference is relative-only — no ``..``, no host-absolute path leaks.
    company_root = tmp_path / "acme"
    workspace = CompanyWorkspace(company_root)
    (workspace.worktree_for("ada").path / "feature.py").write_text("x\n", encoding="utf-8")

    artifact = await engineer_lander(company_root).land(
        Task(id=uid("t1"), intent="ship it", assignee_employee_id="ada"), result=None
    )

    assert artifact.resource_ref["worktree"] == "worktrees/ada"  # relative to the company root
    for value in artifact.resource_ref.values():
        if isinstance(value, str):
            assert not Path(value).is_absolute(), f"{value!r} leaks a host path"
            assert ".." not in value


async def test_merge_conflict_is_recorded_not_raised(tmp_path: Path) -> None:
    # a conflicting integration must not raise or leave the repo mid-merge — the PR is still recorded
    # (branch + commit), just flagged ``merged=False`` for a human/reviewer to resolve.
    company_root = tmp_path / "acme"
    workspace = CompanyWorkspace(company_root)
    wt = workspace.worktree_for("ada")
    (wt.path / "calc.py").write_text("ada\n", encoding="utf-8")  # the engineer's version
    # an independent, conflicting change lands on ``main`` first
    (workspace.repo / "calc.py").write_text("main\n", encoding="utf-8")
    _git(workspace.repo, "add", "-A")
    _git(workspace.repo, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-m", "main edit")

    artifact = await engineer_lander(company_root).land(
        Task(id=uid("t1"), intent="ship it", assignee_employee_id="ada"), result=None
    )

    assert artifact.resource_ref["merged"] is False  # not integrated
    assert artifact.resource_ref["commit"]  # but the PR is still recorded
    # the repo is left clean (the conflicted merge was aborted, not left in progress)
    assert _git(workspace.repo, "status", "--porcelain") == ""
