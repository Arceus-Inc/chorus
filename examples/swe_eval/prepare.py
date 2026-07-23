"""Prepare a case's starting repo state: clone (cached) and export the tree at ``base_commit``.

The Chorus factory seeds a worktree cleanest from a *plain directory* (``_copy_tree`` copies it and
commits it as ``main``); seeding from a git repo would clone the default branch's HEAD, not our detached
``base_commit``. So we export the exact commit's tree with ``git archive`` (+ Python ``tarfile``, so no
shell pipe or external ``tar``) into a ``.git``-free seed dir. Clones are cached per repo and reused.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
from pathlib import Path


class PrepareError(RuntimeError):
    """Cloning or exporting the base commit failed."""


def _git(
    *args: str, cwd: Path | None = None, timeout_s: float = 600.0
) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return proc


def _slug(repo: str) -> str:
    return repo.replace("/", "__").replace(":", "_")


def ensure_clone(clone_url: str, repo: str, cache_root: Path) -> Path:
    """Clone ``clone_url`` into ``cache_root/<slug>`` once; reuse it thereafter. Returns the clone dir."""
    cache_root.mkdir(parents=True, exist_ok=True)
    dest = cache_root / _slug(repo)
    if (dest / ".git").exists():
        return dest
    res = _git("clone", "--no-single-branch", clone_url, str(dest), timeout_s=1200.0)
    if res.returncode != 0:
        raise PrepareError(f"git clone {clone_url} failed: {res.stderr.strip()[:400]}")
    return dest


def _ensure_commit(clone: Path, base_commit: str) -> None:
    """Make sure ``base_commit`` exists locally; fetch it if the shallow/partial clone lacks it."""
    if _git("cat-file", "-e", f"{base_commit}^{{commit}}", cwd=clone).returncode == 0:
        return
    # Try a targeted fetch, then a full fetch as a fallback.
    if _git("fetch", "origin", base_commit, cwd=clone, timeout_s=1200.0).returncode == 0:
        if _git("cat-file", "-e", f"{base_commit}^{{commit}}", cwd=clone).returncode == 0:
            return
    _git("fetch", "--all", "--tags", cwd=clone, timeout_s=1200.0)
    if _git("cat-file", "-e", f"{base_commit}^{{commit}}", cwd=clone).returncode != 0:
        raise PrepareError(f"base_commit {base_commit[:12]} not found in clone after fetch")


def export_base_state(
    clone_url: str, repo: str, base_commit: str, *, cache_root: Path, seed_dir: Path
) -> Path:
    """Export the repo's tree at ``base_commit`` into ``seed_dir`` (a clean, ``.git``-free directory).

    Returns ``seed_dir``, ready to hand to ``EmployeeHarnessFactory(seed=seed_dir)``.
    """
    clone = ensure_clone(clone_url, repo, cache_root)
    _ensure_commit(clone, base_commit)

    if seed_dir.exists():
        shutil.rmtree(seed_dir, ignore_errors=True)
    seed_dir.mkdir(parents=True, exist_ok=True)

    tar_path = seed_dir.parent / f"{seed_dir.name}.tar"
    res = _git(
        "archive", "--format=tar", "-o", str(tar_path), base_commit, cwd=clone, timeout_s=600.0
    )
    if res.returncode != 0:
        raise PrepareError(f"git archive {base_commit[:12]} failed: {res.stderr.strip()[:400]}")
    try:
        with tarfile.open(tar_path) as tf:
            _safe_extract(tf, seed_dir)
    finally:
        tar_path.unlink(missing_ok=True)
    return seed_dir


def _safe_extract(tf: tarfile.TarFile, dest: Path) -> None:
    """Extract ``tf`` into ``dest``, refusing any member that escapes it (tar path-traversal guard)."""
    dest = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(dest)):
            raise PrepareError(f"unsafe path in archive: {member.name}")
    tf.extractall(dest)
