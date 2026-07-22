"""Shared commit authorship for outcome landers — attribute git commits to the employee.

An outcome lander snapshots (and sometimes merges) an employee's worktree. Without this, every commit
is authored by the ``chorus`` machine identity with a generic message ("chorus: snapshot work"). These
helpers derive the employee's git-author :class:`~chorus.workspace.Identity` (its real display name when
the ledger is present) and a meaningful commit message from the task's own intent — so the company's
git history reads as real, attributed work rather than anonymous machine snapshots.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chorus.workspace import Identity

if TYPE_CHECKING:
    from chorus.ledger import Ledger, Task


def author_for(employee_id: str, ledger: Ledger | None) -> Identity:
    """The employee's git-author identity — its real display name when the ledger is available."""
    name: str | None = None
    if ledger is not None:
        employee = ledger.employees.get(employee_id)
        name = employee.name if employee is not None else None
    return Identity.for_employee(employee_id, name)


def commit_message(task: Task) -> str:
    """A meaningful commit summary from the task's own intent (its first line, trimmed).

    The intent is the CEO/lead-authored directive for the deliverable, so it reads as a real commit
    subject. Falls back to the task id when a task carries no intent.
    """
    intent = (task.intent or "").strip()
    first_line = intent.splitlines()[0].strip() if intent else ""
    return first_line[:100] if first_line else f"chorus: land task {task.id}"


__all__ = ["author_for", "commit_message"]
