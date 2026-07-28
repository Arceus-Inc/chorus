"""Cross-beat resume directive — canonical text is in Dream ``core-beliefs.md``.

Standing orders inject this at session start. Kept here only if a caller wants
the string without parsing the markdown file.
"""

from __future__ import annotations

RESUME_DIRECTIVE = (
    "RESUME, DON'T RESTART: keep a durable checklist with `todo_write` in `TODO.md`, check items "
    "off as you go, and read it first every beat — reconcile against git/artifacts, then continue "
    "unchecked steps. Never restart from scratch when checklist + work already sit in the worktree. "
    "Load `cross-beat-resume` via `skill` for the full protocol and budget-flush rules."
)

__all__ = ["RESUME_DIRECTIVE"]
