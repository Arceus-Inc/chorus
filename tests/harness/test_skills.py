"""``materialize_skills`` — copy a role's skill bundle into the worktree so the model can read it.

chorus confines dream's file tools to the employee's worktree (``working_dir``), so a skill package
that lives *outside* the worktree (in the installed employee package) is unreachable — the model can
read the injected SKILL.md body but not the bundled files it references. Materializing the bundle into
``.harness/skills/`` (already git-excluded, so it never lands) is what makes those references reachable
by ``read_file``. The copy is read-only: a beat may read the bundle but never mutate it.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from chorus_harness._skills import materialize_skills

pytestmark = pytest.mark.unit


def _bundle(root: Path) -> Path:
    """A source skill package: one skill dir with a body + a subdir'd reference + a template."""
    skill = root / "recommendation-canvas"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# canvas body", encoding="utf-8")
    (skill / "template.md").write_text("THE TEMPLATE", encoding="utf-8")
    (skill / "references" / "sample.md").write_text("A SAMPLE", encoding="utf-8")
    return root


def test_copies_the_whole_bundle_under_harness_skills(tmp_path: Path) -> None:
    source = _bundle(tmp_path / "pkg")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    dest = materialize_skills(worktree, source)

    assert dest == worktree / ".harness" / "skills"
    canvas = dest / "recommendation-canvas"
    assert (canvas / "SKILL.md").read_text(encoding="utf-8") == "# canvas body"
    assert (canvas / "template.md").read_text(encoding="utf-8") == "THE TEMPLATE"
    assert (canvas / "references" / "sample.md").read_text(encoding="utf-8") == "A SAMPLE"


def test_materialised_bundle_is_read_only(tmp_path: Path) -> None:
    source = _bundle(tmp_path / "pkg")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    dest = materialize_skills(worktree, source)

    template = dest / "recommendation-canvas" / "template.md"
    assert not template.stat().st_mode & stat.S_IWUSR  # owner-write cleared
    with pytest.raises(PermissionError):
        template.write_text("tampered", encoding="utf-8")


def test_re_materialising_replaces_the_prior_copy(tmp_path: Path) -> None:
    """Idempotent per beat: a second materialize reflects the source and never trips on read-only."""
    source = _bundle(tmp_path / "pkg")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    materialize_skills(worktree, source)
    # The source drops a file; re-materializing must mirror it (no stale leftovers, no crash).
    (source / "recommendation-canvas" / "template.md").unlink()
    dest = materialize_skills(worktree, source)

    assert not (dest / "recommendation-canvas" / "template.md").exists()
    assert (dest / "recommendation-canvas" / "SKILL.md").exists()
