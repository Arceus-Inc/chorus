"""The cross-beat resumption directive — short pointer; full protocol lives in a skill.

Granting the ``todo_write`` tool is not enough: without an instruction to use it, the model never keeps
a checklist. The long reconcile protocol is loaded on demand via ``skill(name='cross-beat-resume')``
so the invariant system prompt stays small. Read-only roles (reviewer) don't get ``todo_write`` and so
never see this text.
"""

from __future__ import annotations

RESUME_DIRECTIVE = (
    "RESUME, DON'T RESTART: keep a durable checklist with `todo_write` in `TODO.md`, check items "
    "off as you go, and read it first every beat — reconcile against git/artifacts, then continue "
    "unchecked steps. Never restart from scratch when checklist + work already sit in the worktree. "
    "Load `cross-beat-resume` via `skill` for the full protocol and budget-flush rules."
)

__all__ = ["RESUME_DIRECTIVE"]
