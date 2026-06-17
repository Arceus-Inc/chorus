"""CompanyWorkspace — per-employee git-worktree isolation under a shared company root.

Real git in a tmp dir (no mocks): the primitive's whole job is correct git side-effects, so the
tests drive actual ``git init`` / ``worktree add`` / ``merge`` and assert on the resulting trees and
branches. This is the spec 04 §4 containment primitive: every employee of a company writes in its own
branch-isolated worktree, and that work merges back to the company ``main`` later.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chorus.workspace import CompanyWorkspace

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_ensure_repo_creates_a_main_repo_with_an_initial_commit(tmp_path: Path) -> None:
    ws = CompanyWorkspace(tmp_path / "acme")
    repo = ws.ensure_repo()
    assert (repo / ".git").exists()
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"  # the empty root commit
    # idempotent — a second ensure does not re-init or add a commit
    ws.ensure_repo()
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"


def test_worktree_for_creates_a_branch_isolated_workspace(tmp_path: Path) -> None:
    ws = CompanyWorkspace(tmp_path / "acme")
    wt = ws.worktree_for("ada")
    assert wt.path.is_dir()
    assert wt.path == tmp_path / "acme" / "worktrees" / "ada"
    assert wt.branch == "chorus/ada"
    assert _git(wt.path, "rev-parse", "--abbrev-ref", "HEAD") == "chorus/ada"
    # reuse is idempotent — same path, no error
    assert ws.worktree_for("ada").path == wt.path


def test_two_employees_are_isolated_from_each_other(tmp_path: Path) -> None:
    ws = CompanyWorkspace(tmp_path / "acme")
    ada = ws.worktree_for("ada")
    bob = ws.worktree_for("bob")
    (ada.path / "feature.py").write_text("# ada's work\n", encoding="utf-8")
    # bob does not see ada's uncommitted file — different worktrees
    assert not (bob.path / "feature.py").exists()


def test_merge_integrates_an_employee_branch_into_company_main(tmp_path: Path) -> None:
    ws = CompanyWorkspace(tmp_path / "acme")
    repo = ws.ensure_repo()
    ada = ws.worktree_for("ada")
    (ada.path / "feature.py").write_text("print('shipped')\n", encoding="utf-8")
    result = ws.merge("ada")  # snapshots uncommitted work, then merges into main
    assert result.merged is True
    assert result.conflicted is False
    # main now carries ada's deliverable
    assert (repo / "feature.py").read_text(encoding="utf-8") == "print('shipped')\n"


def test_operational_files_are_excluded_from_the_branch(tmp_path: Path) -> None:
    ws = CompanyWorkspace(tmp_path / "acme")
    ada = ws.worktree_for("ada")
    # dream/chorus operational artefacts the harness writes into the working dir
    (ada.path / "roles").mkdir()
    (ada.path / "roles" / "generator.toml").write_text("x", encoding="utf-8")
    (ada.path / "real.py").write_text("y", encoding="utf-8")
    status = _git(ada.path, "status", "--porcelain")
    assert "real.py" in status  # a real deliverable is tracked
    assert "roles/" not in status and "generator.toml" not in status  # operational, excluded
