"""The CEO's outcome lander — "done" means a directive landed where a reviewer can read it (spec 04 §2).

A CEO's deliverable is a written directive in its worktree. This lander snapshots the assignee's
branch-isolated worktree (commits the directive on ``chorus/{employee}``) and returns the canonical
``directive`` :class:`~chorus.outcomes.Artifact` (an ``ArtifactType.DOC``) pointing at the file — branch
+ commit + a relative worktree pointer, never a host-absolute path.

Dream-free: pure git (via :class:`~chorus.workspace.CompanyWorkspace`) + ledger-free metadata. The doc
is recorded whether or not it is present (``present``); the DoD is what gates an *absent* directive from
ever reaching ``done``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee._authorship import author_for, commit_message
from chorus_employee.ceo._brief import CEO_DIRECTIVE_DOC

if TYPE_CHECKING:
    from pathlib import Path

    from chorus.ledger import Ledger, Task


class CeoLander:
    """Land a passed CEO beat as a ``directive`` artifact (the committed directive file)."""

    outcome_kind = "directive"

    def __init__(self, company_root: Path, ledger: Ledger | None = None) -> None:
        self._company_root = company_root
        self._ledger = ledger

    async def land(self, task: Task, result: Any) -> Artifact:
        """Snapshot the assignee's worktree and return the ``directive`` artifact for its directive file."""
        del result  # the deliverable is the worktree's directive file, not the beat output
        employee_id = task.assignee_employee_id
        if employee_id is None:
            raise ValueError(f"task {task.id!r} has no assignee — cannot land a directive")
        workspace = CompanyWorkspace(self._company_root)
        doc = workspace.worktree_for(employee_id).path / CEO_DIRECTIVE_DOC
        present = doc.is_file() and doc.stat().st_size > 0
        commit = workspace.snapshot(
            employee_id, author=author_for(employee_id, self._ledger), message=commit_message(task)
        )  # commit the directive on chorus/{employee}
        return Artifact(
            task_id=task.id,
            type=ArtifactType.DOC,
            is_primary=True,
            resource_ref={
                "kind": "directive_doc",
                "branch": f"chorus/{employee_id}",
                "commit": commit,
                "doc": CEO_DIRECTIVE_DOC,  # relative to the worktree — no host path
                "present": present,
            },
        )


def ceo_lander(company_root: Path, ledger: Ledger | None = None) -> CeoLander:
    """The CEO's :class:`~chorus.outcomes.OutcomeLander`, rooted at the org workspace."""
    return CeoLander(company_root, ledger)


__all__ = ["CeoLander", "ceo_lander"]
