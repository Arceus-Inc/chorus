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


def test_publish_to_main_lands_a_file_on_main_and_is_idempotent(tmp_path: Path) -> None:
    ws = CompanyWorkspace(tmp_path / "acme")
    sha1 = ws.publish_to_main("AGENTS.md", "# AGENTS.md\nv1\n", message="chorus: publish contract")
    assert (ws.repo / "AGENTS.md").read_text(encoding="utf-8") == "# AGENTS.md\nv1\n"
    assert _git(ws.repo, "rev-parse", "HEAD") == sha1
    # idempotent — re-publishing identical content makes no new commit
    sha2 = ws.publish_to_main("AGENTS.md", "# AGENTS.md\nv1\n", message="chorus: publish contract")
    assert sha2 == sha1
    # a real change advances main
    sha3 = ws.publish_to_main("AGENTS.md", "# AGENTS.md\nv2\n", message="chorus: publish contract")
    assert sha3 != sha1


def test_worktree_cut_after_publish_carries_the_contract(tmp_path: Path) -> None:
    # spec 15 §4.1: the contract lands on main BEFORE the engineer branches, so the engineer's worktree
    # (cut from main at first request) inherits the real AGENTS.md rather than a placeholder.
    ws = CompanyWorkspace(tmp_path / "acme")
    ws.publish_to_main("AGENTS.md", "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — entry\n",
                       message="chorus: publish contract")
    eng = ws.worktree_for("ada")
    assert (eng.path / "AGENTS.md").is_file()
    assert "Module map" in (eng.path / "AGENTS.md").read_text(encoding="utf-8")


def test_sync_to_main_pulls_landed_work_despite_an_uncommitted_local_file(tmp_path: Path) -> None:
    # The run-6 false block: the manager authored AGENTS.md in its worktree at kickoff (never committed),
    # then children landed code on main. sync_to_main must commit the local file first so `git merge`
    # isn't refused — otherwise the manager reviews an empty tree and the gate reports no_deliverable.
    ws = CompanyWorkspace(tmp_path / "acme")
    mgr = ws.worktree_for("moe")
    (mgr.path / "AGENTS.md").write_text("# AGENTS.md\nv1\n", encoding="utf-8")  # uncommitted, like kickoff
    # a child lands a module on main after the manager's worktree was cut
    ws.publish_to_main("prefrank/core.py", "VALUE = 1\n", message="chorus: child landed core.py")
    assert ws.sync_to_main("moe") is True
    assert (mgr.path / "prefrank" / "core.py").is_file()  # the manager now sees the landed deliverable
    assert (mgr.path / "AGENTS.md").read_text(encoding="utf-8") == "# AGENTS.md\nv1\n"  # its work kept


def test_restore_from_main_reverts_an_engineers_edit_to_a_locked_path(tmp_path: Path) -> None:
    # The acceptance-suite lock (spec 15 §4.2): a locked dir lives on main; an engineer that weakens it
    # in its worktree has the change reverted to main's version before its branch is snapshotted.
    ws = CompanyWorkspace(tmp_path / "acme")
    ws.publish_to_main("acceptance/test_acceptance.py", "def test_real():\n    assert hard_property()\n",
                       message="chorus: publish acceptance suite")
    eng = ws.worktree_for("ada")
    (eng.path / "acceptance" / "test_acceptance.py").write_text(
        "def test_real():\n    assert True  # weakened!\n", encoding="utf-8"
    )
    ws.restore_from_main("ada", "acceptance")  # restore the whole locked dir
    assert "hard_property()" in (eng.path / "acceptance" / "test_acceptance.py").read_text(encoding="utf-8")


def test_restore_from_main_is_a_noop_when_the_path_is_absent_on_main(tmp_path: Path) -> None:
    ws = CompanyWorkspace(tmp_path / "acme")
    ws.worktree_for("ada")
    ws.restore_from_main("ada", "acceptance")  # not on main → best-effort no-op, no raise


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
    (ada.path / "real.py").write_text("y", encoding="utf-8")
    status = _git(ada.path, "status", "--porcelain")
    assert "real.py" in status  # a real deliverable is tracked
    assert ".harness/" not in status and "generator.toml" not in status  # operational, excluded


def test_build_output_and_dream_artifacts_are_excluded(tmp_path: Path) -> None:
    # tier-3 3.4: compiled build output (a Rust crate's target/ — the tinyvec 1241-file leak) and dream's
    # planning artefacts (docs/evals, docs/exec-plans written into the worktree) must NOT land in the
    # deliverable. The engineer's actual source under src/ still does.
    ws = CompanyWorkspace(tmp_path / "acme")
    ada = ws.worktree_for("ada")
    (ada.path / "target" / "release").mkdir(parents=True)
    (ada.path / "target" / "release" / "libtinyvec.rlib").write_text("BLOB", encoding="utf-8")
    (ada.path / "docs" / "evals" / "run_x").mkdir(parents=True)
    (ada.path / "docs" / "evals" / "run_x" / "sprint-1.json").write_text("{}", encoding="utf-8")
    (ada.path / "docs" / "exec-plans").mkdir(parents=True)
    (ada.path / "docs" / "exec-plans" / "plan.json").write_text("{}", encoding="utf-8")
    (ada.path / "src").mkdir()
    (ada.path / "src" / "lib.rs").write_text("pub fn f() {}", encoding="utf-8")
    (ada.path / "docs" / "guide.md").write_text("# real docs", encoding="utf-8")  # genuine docs stay

    status = _git(ada.path, "status", "--porcelain", "-uall")  # -uall: list files inside untracked dirs
    assert "src/lib.rs" in status  # the real source is tracked
    assert "docs/guide.md" in status  # genuine (non-artefact) docs are tracked
    assert "target/" not in status  # the Rust build dir is excluded (no 1241-file leak)
    assert "docs/evals/" not in status  # dream's eval artefacts excluded
    assert "exec-plans/" not in status  # dream's exec-plan artefacts excluded
