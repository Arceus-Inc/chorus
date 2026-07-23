"""The company-state packet — ledger truth mirrored into an executive beat's worktree.

An executive review's subject is the company itself: the goal tree, who is doing what, what is
open, what is being spent. That ground truth lives in the ledger; a beat's evidence must live
in its worktree (the evaluator judges files, never invisible tool calls). This mirror closes
the gap: ``write_company_state`` renders the packet as ``company_state.json`` so the directive
can cite a real file. Written for any role holding ``governance_read`` — the executive
signature — not for a named role.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chorus.ledger import Goal, Ledger

COMPANY_STATE_DOC = "company_state.json"

_TERMINAL_TASK_STATUSES = {"cancelled", "done", "rejected"}


def _goal_rows(ledger: Ledger) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def walk(parent_id: str | None) -> None:
        for goal in ledger.goals.children(parent_id):
            rows.append(_goal_row(goal))
            walk(goal.id)

    walk(None)
    return rows


def _goal_row(goal: Goal) -> dict[str, object]:
    return {
        "id": goal.id,
        "title": goal.title,
        "level": goal.level.value,
        "status": goal.status,
        "parent_id": goal.parent_id,
        "owner": goal.owner_employee_id,
    }


def write_company_state(ledger: Ledger, working_dir: Path) -> Path:
    """Render the packet into ``working_dir`` and return its path."""
    packet = {
        "goals": _goal_rows(ledger),
        "workforce": [
            {
                "id": employee.id,
                "name": employee.name,
                "role": employee.role,
                "status": employee.status.value,
                "reports_to": employee.reports_to,
                "budget_monthly_cents": employee.budget_monthly_cents,
                "spent_monthly_cents": employee.spent_monthly_cents,
                "last_beat_at": employee.last_beat_at,
            }
            for employee in ledger.employees.list()
        ],
        "open_tasks": [
            {
                "id": task.id,
                "intent": task.intent[:300],
                "status": task.status.value,
                "assignee": task.assignee_employee_id,
                "goal_id": task.goal_id,
                "parent_id": task.parent_id,
            }
            for task in ledger.tasks.all()
            if task.status.value not in _TERMINAL_TASK_STATUSES
        ],
    }
    path = working_dir / COMPANY_STATE_DOC
    path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    return path


__all__ = ["COMPANY_STATE_DOC", "write_company_state"]
