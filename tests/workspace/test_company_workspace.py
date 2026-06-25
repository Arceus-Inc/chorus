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


def _seed_git_repo(path: Path) -> Path:
    """A throwaway source git repo with one tracked file + a real commit."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "app.py").write_text("print('upstream')\n", encoding="utf-8")
    _git(path, "add", "-A")
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=u", "-c", "user.email=u@x", "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return path


def test_seed_from_a_git_repo_puts_real_code_on_main(tmp_path: Path) -> None:
    source = _seed_git_repo(tmp_path / "source")
    ws = CompanyWorkspace(tmp_path / "acme", seed=source)
    repo = ws.ensure_repo()
    # the company main carries the source's committed code, on a branch named main
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('upstream')\n"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_employee_branches_off_seeded_code(tmp_path: Path) -> None:
    source = _seed_git_repo(tmp_path / "source")
    ws = CompanyWorkspace(tmp_path / "acme", seed=source)
    ada = ws.worktree_for("ada")
    # the employee's isolated worktree starts from the real codebase, not a blank tree
    assert (ada.path / "app.py").read_text(encoding="utf-8") == "print('upstream')\n"


def test_seed_from_a_plain_directory_commits_its_files(tmp_path: Path) -> None:
    src = tmp_path / "proj"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    ws = CompanyWorkspace(tmp_path / "acme", seed=src)
    repo = ws.ensure_repo()
    assert (repo / "pkg" / "mod.py").read_text(encoding="utf-8") == "X = 1\n"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_plain_directory_seed_preserves_declarative_harness_surface_config(
    tmp_path: Path,
) -> None:
    src = tmp_path / "proj"
    harness = src / ".harness"
    harness.mkdir(parents=True)
    (harness / "mcp-allowlist.toml").write_text("[[mcp]]\nname = 'demo'\n", encoding="utf-8")
    (harness / "plugins-enabled.toml").write_text(
        "[[plugin]]\nname = 'surface-probe'\n", encoding="utf-8"
    )
    (harness / "mcp-credentials.toml").write_text("secret = 'nope'\n", encoding="utf-8")
    (harness / "runtime.json").write_text("{}\n", encoding="utf-8")

    ws = CompanyWorkspace(tmp_path / "acme", seed=src)
    repo = ws.ensure_repo()

    assert (repo / ".harness" / "mcp-allowlist.toml").exists()
    assert (repo / ".harness" / "plugins-enabled.toml").exists()
    assert not (repo / ".harness" / "mcp-credentials.toml").exists()
    assert not (repo / ".harness" / "runtime.json").exists()


def test_plain_directory_seed_skips_nested_chorus_workspace(tmp_path: Path) -> None:
    src = tmp_path / "proj"
    (src / ".chorus" / "work" / "company" / "repo").mkdir(parents=True)
    (src / ".chorus" / "work" / "company" / "repo" / "loop.txt").write_text(
        "loop\n", encoding="utf-8"
    )
    (src / "chorus" / ".chorus" / "work" / "company" / "repo").mkdir(parents=True)
    (src / "chorus" / ".chorus" / "work" / "company" / "repo" / "nested.txt").write_text(
        "nested\n", encoding="utf-8"
    )
    (src / "chorus" / ".pytest_cache").mkdir(parents=True)
    (src / "chorus" / ".pytest_cache" / "cache.txt").write_text("cache\n", encoding="utf-8")
    (src / "chorus" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (src / "README.md").write_text("# ok\n", encoding="utf-8")

    ws = CompanyWorkspace(src / ".chorus" / "work" / "company", seed=src)
    repo = ws.ensure_repo()

    assert (repo / "README.md").read_text(encoding="utf-8") == "# ok\n"
    assert (repo / "chorus" / "app.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert not (repo / ".chorus").exists()
    assert not (repo / "chorus" / ".chorus").exists()
    assert not (repo / "chorus" / ".pytest_cache").exists()


def test_operational_files_are_excluded_from_the_branch(tmp_path: Path) -> None:
    ws = CompanyWorkspace(tmp_path / "acme")
    ada = ws.worktree_for("ada")
    # dream/chorus operational artefacts the harness writes into the working dir
    (ada.path / ".harness" / "roles").mkdir(parents=True)
    (ada.path / ".harness" / "roles" / "generator.toml").write_text("x", encoding="utf-8")
    (ada.path / "docs" / "exec-plans" / "active").mkdir(parents=True)
    (ada.path / "docs" / "exec-plans" / "active" / "run.json").write_text("{}", encoding="utf-8")
    (ada.path / "docs" / "evals" / "run_1").mkdir(parents=True)
    (ada.path / "docs" / "evals" / "run_1" / "sprint-1.json").write_text("{}", encoding="utf-8")
    (ada.path / "real.py").write_text("y", encoding="utf-8")
    status = _git(ada.path, "status", "--porcelain")
    assert "real.py" in status  # a real deliverable is tracked
    assert ".harness/" not in status and "generator.toml" not in status  # operational, excluded
    assert "docs/exec-plans" not in status and "docs/evals" not in status


def test_sync_to_main_ignores_dream_operational_docs(tmp_path: Path) -> None:
    ws = CompanyWorkspace(tmp_path / "acme")
    repo = ws.ensure_repo()
    ada = ws.worktree_for("ada")
    manager = ws.worktree_for("max")

    (ada.path / "app.py").write_text("print('shipped')\n", encoding="utf-8")
    assert ws.merge("ada").merged is True

    (manager.path / "docs" / "exec-plans" / "active").mkdir(parents=True)
    (manager.path / "docs" / "exec-plans" / "active" / "run.json").write_text("{}", encoding="utf-8")
    (manager.path / "docs" / "evals" / "run_1").mkdir(parents=True)
    (manager.path / "docs" / "evals" / "run_1" / "sprint-1.json").write_text("{}", encoding="utf-8")

    assert ws.sync_to_main("max") is True
    assert (manager.path / "app.py").read_text(encoding="utf-8") == "print('shipped')\n"
    assert _git(repo, "rev-parse", "main") == _git(manager.path, "rev-parse", "HEAD")
