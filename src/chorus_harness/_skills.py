"""Materialize a role's skill bundle into the worktree so the model can read its bundled files.

Anthropic's Agent Skills reach a skill's bundled files — ``references/``, ``template.md``, scripts —
through the agent's ordinary file tools against the filesystem (progressive disclosure). chorus
confines those tools to the employee's worktree (the harness ``working_dir``), so a skill package that
ships *inside* the installed employee package is out of reach until we copy it *in*.

We copy it under ``.harness/skills/`` — already excluded from every worktree branch by the workspace's
``info/exclude`` (see :mod:`chorus.workspace`), so the bundle is reachable by ``read_file`` yet never
committed or merged as a deliverable — and set it read-only, so a beat may read the bundle but never
mutate it (the guardrail). The copy is regenerated per beat, so it always mirrors the canonical source.
"""

from __future__ import annotations

import shutil
import stat
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


def materialize_skills(harness_dir: Path, skills_root: str | Path) -> Path:
    """Copy the skill bundle at ``skills_root`` into ``harness_dir/.harness/skills`` (read-only).

    Returns the destination — the ``project_dir`` to point dream's skill registry at, so both dream's
    SKILL.md load and the model's reference reads resolve to the same in-worktree, git-excluded copy.
    Idempotent: re-materializing replaces the prior copy (the factory rebuilds the harness per beat).
    """
    dest = harness_dir.joinpath(*_SKILLS_SUBDIR)
    if dest.exists():
        _restore_writable(dest)
        shutil.rmtree(dest)
    shutil.copytree(Path(skills_root), dest)
    _set_read_only(dest)
    return dest


def materialize_lattice_skills_into(skills_dir: Path) -> None:
    """Merge chorus-owned lattice agent skills into an existing materialized skills directory."""
    from chorus_employee._lattice import LATTICE_SKILLS_ROOT

    root = LATTICE_SKILLS_ROOT
    if not root.is_dir():
        return
    skills_dir.mkdir(parents=True, exist_ok=True)
    _restore_writable(skills_dir)
    for skill_dir in sorted(root.iterdir()):
        if not skill_dir.is_dir():
            continue
        if not (skill_dir / "SKILL.md").exists():
            continue
        target = skills_dir / skill_dir.name
        if target.exists():
            _restore_writable(target)
            shutil.rmtree(target)
        shutil.copytree(skill_dir, target)
    _set_read_only(skills_dir)


def _strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1 :]).lstrip("\n")
    return text


def _merge_evolved_into_canonical(canonical: str, evolved: str) -> str:
    """Keep canonical frontmatter + body; append evolved body sections once."""
    evolved_body = _strip_frontmatter(evolved).strip()
    if not evolved_body:
        return canonical
    # Idempotent: if the evolved section heading already exists, replace from that heading.
    heading = ""
    for line in evolved_body.splitlines():
        if line.startswith("## "):
            heading = line.strip()
            break
    if heading and heading in canonical:
        before, _, _rest = canonical.partition(heading)
        return before.rstrip() + "\n\n" + evolved_body + "\n"
    return canonical.rstrip() + "\n\n" + evolved_body + "\n"


def materialize_versioned_skills_into(
    skills_dir: Path,
    *,
    company_root: Path,
    employee_id: str,
) -> None:
    """Materialize Chorus SkillStore HEAD (or pin) into the worktree skills dir.

    DB is source of truth; this is the Dream/adapter cache. Evolved skills merge
    into an existing canonical ``SKILL.md`` (preserve Dream frontmatter). Created
    skills are written as full packages from ``file_inventory``.
    """
    from chorus.skills import SkillOrigin, SkillStore

    store = SkillStore(Path(company_root) / "skills")
    try:
        active = store.list_active(employee_id)
        if not active:
            return
        skills_dir.mkdir(parents=True, exist_ok=True)
        _restore_writable(skills_dir)
        for skill in active:
            rev = store.resolve_inventory(employee_id, skill.slug)
            if rev is None:
                continue
            inventory = rev.inventory()
            skill_md = ""
            for entry in inventory:
                if entry.get("path") == "SKILL.md":
                    skill_md = str(entry.get("content") or "")
                    break
            if not skill_md and inventory:
                skill_md = str(inventory[0].get("content") or "")
            if not skill_md:
                continue
            target = skills_dir / skill.slug
            target_md = target / "SKILL.md"
            if target_md.exists() and skill.origin is SkillOrigin.EVOLVED:
                _restore_writable(target)
                canonical_text = target_md.read_text(encoding="utf-8")
                target_md.write_text(
                    _merge_evolved_into_canonical(canonical_text, skill_md),
                    encoding="utf-8",
                )
            else:
                target.mkdir(parents=True, exist_ok=True)
                if target_md.exists():
                    _restore_writable(target)
                target_md.write_text(skill_md, encoding="utf-8")
                for entry in inventory:
                    rel = str(entry.get("path") or "")
                    if not rel or rel == "SKILL.md":
                        continue
                    # path traversal guard
                    dest = (target / rel).resolve()
                    if not str(dest).startswith(str(target.resolve())):
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(str(entry.get("content") or ""), encoding="utf-8")
        _set_read_only(skills_dir)
    finally:
        store.close()


__all__ = [
    "materialize_skills",
    "materialize_lattice_skills_into",
    "materialize_versioned_skills_into",
]
