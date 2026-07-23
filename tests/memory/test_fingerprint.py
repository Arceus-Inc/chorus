"""The beat fingerprint — files a beat touched, straight from git (spec 07 §4).

Covers the three git states a beat leaves behind (committed-by-lander, uncommitted,
untracked) in one call, and the best-effort exits (no baseline, no worktree, non-repo)
that must never raise. Also filters operational noise so recall isn't buried in
``docs/exec-plans/`` / caches / scratch DBs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chorus.memory import beat_fingerprint, is_deliverable_path

pytestmark = pytest.mark.unit


def _git(worktree: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _seeded_repo(tmp_path: Path) -> Path:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    _git(worktree, "init", "-q")
    _git(worktree, "config", "user.email", "t@t")
    _git(worktree, "config", "user.name", "t")
    (worktree / "seed.py").write_text("x = 1\n", encoding="utf-8")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-qm", "seed")
    return worktree


def test_fingerprint_covers_committed_uncommitted_and_untracked(tmp_path: Path) -> None:
    worktree = _seeded_repo(tmp_path)
    base = _git(worktree, "rev-parse", "HEAD")

    (worktree / "a.py").write_text("a = 1\n", encoding="utf-8")  # committed after base (lander)
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-qm", "beat")
    (worktree / "b.py").write_text("b = 1\n", encoding="utf-8")  # tracked, uncommitted
    (worktree / "c.py").write_text("c = 1\n", encoding="utf-8")  # untracked

    assert beat_fingerprint(worktree, base) == ("a.py", "b.py", "c.py")


def test_fingerprint_drops_operational_noise(tmp_path: Path) -> None:
    worktree = _seeded_repo(tmp_path)
    base = _git(worktree, "rev-parse", "HEAD")

    (worktree / "auth" / "service.py").parent.mkdir(parents=True)
    (worktree / "auth" / "service.py").write_text("x=1\n", encoding="utf-8")
    (worktree / "TODO.md").write_text("# TODO\n", encoding="utf-8")
    plans = worktree / "docs" / "exec-plans" / "active"
    plans.mkdir(parents=True)
    (plans / "run_abc.md").write_text("plan\n", encoding="utf-8")
    (worktree / "commerce.db").write_bytes(b"sqlite")
    (worktree / ".harness" / "x.toml").parent.mkdir(parents=True)
    (worktree / ".harness" / "x.toml").write_text("x=1\n", encoding="utf-8")

    assert beat_fingerprint(worktree, base) == ("auth/service.py",)


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        ("auth/service.py", True),
        ("tests/test_auth.py", True),
        ("main.py", True),
        ("TODO.md", False),
        ("docs/exec-plans/active/run_x.md", False),
        ("docs/exec-plans/active/run_x.json", False),
        ("commerce.db", False),
        (".harness/sandbox.toml", False),
        (".dream/ledger.json", False),
        ("__pycache__/x.pyc", False),
    ],
)
def test_is_deliverable_path(path: str, ok: bool) -> None:
    assert is_deliverable_path(path) is ok


def test_fingerprint_none_base_is_empty(tmp_path: Path) -> None:
    worktree = _seeded_repo(tmp_path)
    assert beat_fingerprint(worktree, None) == ()


def test_fingerprint_none_worktree_is_empty() -> None:
    assert beat_fingerprint(None, "deadbeef") == ()


def test_fingerprint_non_repo_is_empty(tmp_path: Path) -> None:
    assert beat_fingerprint(tmp_path / "nope", "deadbeef") == ()
