"""The beat fingerprint — files a beat touched, straight from git (spec 07 §4).

Covers the three git states a beat leaves behind (committed-by-lander, uncommitted,
untracked) in one call, and the best-effort exits (no baseline, no worktree, non-repo)
that must never raise.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chorus.memory import beat_fingerprint

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


def test_fingerprint_none_base_is_empty(tmp_path: Path) -> None:
    worktree = _seeded_repo(tmp_path)
    assert beat_fingerprint(worktree, None) == ()


def test_fingerprint_none_worktree_is_empty() -> None:
    assert beat_fingerprint(None, "deadbeef") == ()


def test_fingerprint_non_repo_is_empty(tmp_path: Path) -> None:
    assert beat_fingerprint(tmp_path / "nope", "deadbeef") == ()
