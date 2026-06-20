"""The Analyst's outcome lander — "done" means a findings doc landed where a reviewer can read it (spec 04 §2).

An Analyst's deliverable is a written findings doc in its worktree. This lander snapshots the
assignee's branch-isolated worktree (commits the findings on ``chorus/{employee}``) and returns the
canonical ``finding`` :class:`~chorus.outcomes.Artifact` pointing at the file — branch + commit + a
relative worktree pointer, never a host-absolute path (spec 04 §2).

Dream-free: pure git (via :class:`~chorus.workspace.CompanyWorkspace`) + ledger-free metadata. The doc
is recorded whether or not it is present (``present``); the DoD is what gates an *absent* findings doc
from ever reaching ``done``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee.analyst._brief import ANALYST_FINDINGS_DOC

if TYPE_CHECKING:
    from pathlib import Path

    from chorus.ledger import Task


class AnalystLander:
    """Land a passed Analyst beat as a ``finding`` artifact (the committed findings file)."""

    outcome_kind = "finding"

    def __init__(self, company_root: Path) -> None:
        self._company_root = company_root

    async def land(self, task: Task, result: Any) -> Artifact:
        """Snapshot the assignee's worktree and return the ``finding`` artifact for its findings file."""
        del result  # the deliverable is the worktree's findings file, not the beat output
        employee_id = task.assignee_employee_id
        if employee_id is None:
            raise ValueError(f"task {task.id!r} has no assignee — cannot land a finding")
        workspace = CompanyWorkspace(self._company_root)
        doc = workspace.worktree_for(employee_id).path / ANALYST_FINDINGS_DOC
        present = doc.is_file() and doc.stat().st_size > 0
        commit = workspace.snapshot(employee_id)  # commit the findings on chorus/{employee}
        return Artifact(
            task_id=task.id,
            type=ArtifactType.FINDING,
            is_primary=True,
            resource_ref={
                "kind": "findings_doc",
                "branch": f"chorus/{employee_id}",
                "commit": commit,
                "doc": ANALYST_FINDINGS_DOC,  # relative to the worktree — no host path
                "present": present,
            },
        )


def analyst_lander(company_root: Path) -> AnalystLander:
    """The Analyst's :class:`~chorus.outcomes.OutcomeLander`, rooted at the org workspace."""
    return AnalystLander(company_root)


__all__ = ["AnalystLander", "analyst_lander"]
