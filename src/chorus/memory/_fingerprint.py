"""The beat's structural fingerprint: which files it touched, straight from git (spec 07 §4).

Derived from the worktree, never parsed from prose — this is the key both episodic recall and
lattice re-grounding use. Best-effort by design: fingerprint capture must never fail a beat, so a
read-only beat (no worktree), a missing baseline, or a non-repo dir yields an empty fingerprint
rather than raising.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git_lines(worktree: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def beat_fingerprint(worktree: Path | None, base_sha: str | None) -> tuple[str, ...]:
    """Repo-relative paths this beat touched since ``base_sha`` — committed, uncommitted, or new.

    ``git diff --name-only <base_sha>`` compares the baseline to the *working tree*, so it catches
    both the lander's commit and any still-uncommitted work in one shot; ``ls-files --others`` adds
    the untracked files. Returns a sorted, de-duplicated tuple, or ``()`` when the fingerprint cannot
    be taken (no worktree, no baseline, or any git failure).
    """
    if worktree is None or base_sha is None:
        return ()
    try:
        tracked = _git_lines(worktree, "diff", "--name-only", base_sha)
        untracked = _git_lines(worktree, "ls-files", "--others", "--exclude-standard")
    except (subprocess.CalledProcessError, OSError):
        return ()
    return tuple(sorted(set(tracked) | set(untracked)))
