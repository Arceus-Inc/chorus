"""Materialize a role's skill bundle into the worktree so the model can read its bundled files.

Anthropic's Agent Skills reach a skill's bundled files — ``references/``, ``template.md``, scripts —
through the agent's ordinary file tools against the filesystem (progressive disclosure). chorus
confines those tools to the employee's worktree (the harness ``working_dir``), so a skill package that
ships *inside* the installed employee package is out of reach until we copy it *in*.

We copy it under ``.harness/skills/`` — already excluded from every worktree branch by the workspace's
``info/exclude`` (see :mod:`chorus.workspace`), so the bundle is reachable by ``read_file`` yet never
committed or merged as a deliverable — and set it read-only, so a beat may read the bundle but never
mutate it (the guardrail). The copy is regenerated per beat, so it always mirrors the canonical source.

Shared cross-cutting skills (``chorus_employee/skills/``) are merged in after the role bundle; a
role-specific skill of the same name wins.
"""

from __future__ import annotations

import shutil
import stat
from collections.abc import Sequence
from pathlib import Path

# Under ``.harness/`` (git-excluded in every worktree), so the materialized bundle never lands.
_SKILLS_SUBDIR = (".harness", "skills")

_READ_ONLY_FILE = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH  # 0o444
_READ_ONLY_DIR = _READ_ONLY_FILE | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH  # 0o555 (traversable)


def _restore_writable(root: Path) -> None:
    """Re-grant owner-write across a read-only tree so a prior materialization can be replaced.

    Removing an entry needs write on its *containing directory*, so every directory (and the root)
    must be made writable before :func:`shutil.rmtree`.
    """
    root.chmod(root.stat().st_mode | stat.S_IWUSR)
    for path in root.rglob("*"):
        path.chmod(path.stat().st_mode | stat.S_IWUSR)


def _set_read_only(root: Path) -> None:
    """Set the whole tree read-only — the beat reads the bundle but cannot write it (the guardrail)."""
    for path in root.rglob("*"):
        path.chmod(_READ_ONLY_DIR if path.is_dir() else _READ_ONLY_FILE)
    root.chmod(_READ_ONLY_DIR)


def _merge_skill_dirs(dest: Path, extra_root: Path) -> None:
    """Copy skill packages from ``extra_root`` into ``dest``; existing names are left alone."""
    if not extra_root.is_dir():
        return
    for child in extra_root.iterdir():
        if not child.is_dir() or not (child / "SKILL.md").is_file():
            continue
        target = dest / child.name
        if target.exists():
            continue
        shutil.copytree(child, target)


def materialize_skills(
    harness_dir: Path,
    skills_root: str | Path,
    *,
    extra_roots: Sequence[Path] = (),
) -> Path:
    """Copy the skill bundle at ``skills_root`` into ``harness_dir/.harness/skills`` (read-only).

    Optional ``extra_roots`` are merged afterward (role-specific names win). Returns the destination —
    the ``project_dir`` to point dream's skill registry at, so both dream's SKILL.md load and the
    model's reference reads resolve to the same in-worktree, git-excluded copy. Idempotent:
    re-materializing replaces the prior copy (the factory rebuilds the harness per beat).
    """
    dest = harness_dir.joinpath(*_SKILLS_SUBDIR)
    if dest.exists():
        _restore_writable(dest)
        shutil.rmtree(dest)
    shutil.copytree(Path(skills_root), dest)
    for extra in extra_roots:
        _merge_skill_dirs(dest, Path(extra))
    _set_read_only(dest)
    return dest


__all__ = ["materialize_skills"]
