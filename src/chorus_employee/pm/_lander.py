"""The PM's outcome lander — "done" means a plan doc landed somewhere a reviewer can read it (spec 04 §2).

A PM's deliverable is a written plan/spec in its worktree. This lander snapshots the assignee's
branch-isolated worktree (commits the plan on ``chorus/{employee}``) and returns the canonical ``doc``
:class:`~chorus.outcomes.Artifact` pointing at the plan file — branch + commit + a relative worktree
pointer, never a host-absolute path (spec 04 §2).

Dream-free: pure git (via :class:`~chorus.workspace.CompanyWorkspace`) + ledger-free metadata. The doc
is recorded whether or not it is present (``present``), so a landing is a faithful strict-completion
record rather than a silent gap; the DoD is what gates an *absent* plan from ever reaching ``done``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee.pm._brief import PM_PLAN_DOC

if TYPE_CHECKING:
    from pathlib import Path

    from chorus.ledger import Task


class PmLander:
    """Land a passed PM beat as a ``doc`` artifact (the committed plan file in its worktree)."""

    outcome_kind = "doc"

    def __init__(self, company_root: Path) -> None:
        self._company_root = company_root

    async def land(self, task: Task, result: Any) -> Artifact:
        """Snapshot the assignee's worktree and return the ``doc`` artifact for its plan file."""
        del result  # the deliverable is the worktree's plan file, not the beat output
        employee_id = task.assignee_employee_id
        if employee_id is None:
            raise ValueError(f"task {task.id!r} has no assignee — cannot land a doc")
        workspace = CompanyWorkspace(self._company_root)
        doc = workspace.worktree_for(employee_id).path / PM_PLAN_DOC
        present = doc.is_file() and doc.stat().st_size > 0
        commit = workspace.snapshot(employee_id)  # commit the plan on chorus/{employee}
        return Artifact(
            task_id=task.id,
            type=ArtifactType.DOC,
            is_primary=True,
            resource_ref={
                "kind": "plan_doc",
                "branch": f"chorus/{employee_id}",
                "commit": commit,
                "doc": PM_PLAN_DOC,  # relative to the worktree — no host path
                "present": present,
            },
        )


def pm_lander(company_root: Path) -> PmLander:
    """The PM's :class:`~chorus.outcomes.OutcomeLander`, rooted at the org workspace."""
    return PmLander(company_root)


__all__ = ["PmLander", "pm_lander"]
