"""The beat's structural fingerprint: which files it touched, straight from git (spec 07 §4).

Derived from the worktree, never parsed from prose — this is the key both episodic recall and
lattice re-grounding use. Best-effort by design: fingerprint capture must never fail a beat, so a
read-only beat (no worktree), a missing baseline, or a non-repo dir yields an empty fingerprint
rather than raising.

Operational noise (harness sidecars, exec-plans, scratch DBs, ``TODO.md``) is filtered out so
``files_touched`` stays a list of *deliverables* an agent can usefully re-open on the next beat —
not a dump of every path git saw.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Path prefixes / exact names that are machinery, not product code — kept out of files_touched so
# recall surfaces auth/, orders/, tests/ instead of docs/exec-plans/ and commerce.db.
_NOISE_PREFIXES: tuple[str, ...] = (
    "docs/exec-plans/",
    "docs/exec-plans",
    ".dream/",
    ".harness/",
    ".chorus/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".venv/",
    "__pycache__/",
    "node_modules/",
    "memory/",
    "roles/",
    "test_evidence/",
    "security_scan/",
    "code_quality/",
)
_NOISE_NAMES: frozenset[str] = frozenset(
    {
        "TODO.md",
        "commerce.db",
        "app.db",
        ".DS_Store",
    }
)
_NOISE_SUFFIXES: tuple[str, ...] = (".db", ".pyc", ".pyo")


def is_deliverable_path(path: str) -> bool:
    """True when ``path`` is product code / tests an agent should care about on resume."""
    if not path or path in _NOISE_NAMES:
        return False
    name = path.rsplit("/", 1)[-1]
    if name in _NOISE_NAMES:
        return False
    if any(path == p.rstrip("/") or path.startswith(p) for p in _NOISE_PREFIXES):
        return False
    return not any(path.endswith(sfx) for sfx in _NOISE_SUFFIXES)


def _git_lines(worktree: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def beat_fingerprint(worktree: Path | None, base_sha: str | None) -> tuple[str, ...]:
    """Repo-relative deliverable paths this beat touched since ``base_sha``.

    ``git diff --name-only <base_sha>`` compares the baseline to the *working tree*, so it catches
    both the lander's commit and any still-uncommitted work in one shot; ``ls-files --others`` adds
    the untracked files. Operational noise is dropped. Returns a sorted, de-duplicated tuple, or
    ``()`` when the fingerprint cannot be taken (no worktree, no baseline, or any git failure).
    """
    if worktree is None or base_sha is None:
        return ()
    try:
        tracked = _git_lines(worktree, "diff", "--name-only", base_sha)
        untracked = _git_lines(worktree, "ls-files", "--others", "--exclude-standard")
    except (subprocess.CalledProcessError, OSError):
        return ()
    return tuple(sorted(p for p in set(tracked) | set(untracked) if is_deliverable_path(p)))


__all__ = ["beat_fingerprint", "is_deliverable_path"]
