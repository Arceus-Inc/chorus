"""The cross-beat resumption directive — shared by every writer-employee that carries ``todo_write``.

Granting the ``todo_write`` tool is not enough: without an instruction to use it, the model never keeps
a checklist. This directive tells an employee to maintain a durable ``TODO.md`` and resume from it after
a budget-killed beat instead of restarting. It is appended to each writer-employee's brief (the Backend
Engineer states the same protocol inline). Read-only roles (reviewer) don't get ``todo_write`` and so
never see this text.
"""

from __future__ import annotations

RESUME_DIRECTIVE = (
    "RESUME, DON'T RESTART: your work can span more than one beat, and a beat can be killed abruptly "
    "when its budget runs out — but your worktree persists. Keep a durable checklist with the "
    "`todo_write` tool: list the whole task's steps up front in `TODO.md`, and check each off THE "
    "MOMENT it is done (not at the end; the kill is abrupt). The FIRST thing you do every beat is read "
    "`TODO.md` if it exists and reconcile it against reality — `git status` and your artifacts on disk "
    "show what ACTUALLY got done — then resume the unchecked steps. Never restart from scratch when a "
    "checklist and prior work already sit in the worktree."
)

__all__ = ["RESUME_DIRECTIVE"]
