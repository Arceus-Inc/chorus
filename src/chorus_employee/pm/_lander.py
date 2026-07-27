"""The PM's outcome lander — "done" means a plan doc landed somewhere a reviewer can read it (spec 04 §2).

A PM's deliverable is a written plan/spec in its worktree. This lander snapshots the assignee's
branch-isolated worktree (commits the plan on ``chorus/{employee}``), integrates that branch into the
company ``main`` so the plan is visible to the engineers who build from it, and returns the canonical
``doc`` :class:`~chorus.outcomes.Artifact` pointing at the plan file — branch + commit + a relative
worktree pointer, never a host-absolute path (spec 04 §2).

Dream-free: pure git (via :class:`~chorus.workspace.CompanyWorkspace`) + ledger-free metadata. The doc
is recorded whether or not it is present (``present``), so a landing is a faithful strict-completion
record rather than a silent gap; the DoD is what gates an *absent* plan from ever reaching ``done``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee._authorship import author_for, commit_message
from chorus_employee.pm._brief import PM_PLAN_DOC
from chorus_employee.pm._decision import (
    DECISION_MIRROR_DOC,
    render_decision_mirror,
    render_packet,
)

if TYPE_CHECKING:
    from pathlib import Path

    from chorus.ledger import Ledger, Task

_PACKET_DOC = "sources.json"


class PmLander:
    """Land a passed PM beat as a ``doc`` artifact (the committed plan file in its worktree).

    When a ``ledger`` is supplied, the lander also renders the §10 decision packet (``sources.json``)
    from the recorded decision + claim rows and commits it alongside the plan — so a landed decision
    ships with its auditable evidence trail. Without a ledger the packet is skipped (the plan still lands).
    """

    outcome_kind = "doc"

    def __init__(self, company_root: Path, ledger: Ledger | None = None) -> None:
        self._company_root = company_root
        self._ledger = ledger

    async def land(self, task: Task, result: Any) -> Artifact:
        """Snapshot the assignee's worktree, integrate the plan into ``main``, and return the ``doc``."""
        del result  # the deliverable is the worktree's plan file, not the beat output
        employee_id = task.assignee_employee_id
        if employee_id is None:
            raise ValueError(f"task {task.id!r} has no assignee — cannot land a doc")
        workspace = CompanyWorkspace(self._company_root)
        worktree = workspace.worktree_for(employee_id).path
        doc = worktree / PM_PLAN_DOC
        present = doc.is_file() and doc.stat().st_size > 0
        self._write_decision_mirror(worktree, task.id)
        packet_written = self._write_packet(worktree, task.id)
        author = author_for(employee_id, self._ledger)
        message = commit_message(task)
        commit = workspace.snapshot(
            employee_id, author=author, message=message
        )  # commit the plan (+ packet) on chorus/{employee}
        # A plan that never reaches ``main`` is invisible to the engineers who must build to it: like
        # the Engineer's PR, the PM's spec integrates into company ``main`` so a downstream task that
        # ``depends_on`` this one branches off a main that already carries the plan (conflict-safe —
        # a conflicting merge is recorded, not raised). This is what makes the plan a real, shared
        # contract rather than a dead artifact stranded on the PM's branch.
        merge = workspace.merge(employee_id, author=author, message=message)
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
                "packet": _PACKET_DOC if packet_written else None,
                "merged": merge.merged,
                "into": merge.into,
            },
        )

    def _write_decision_mirror(self, worktree: Path, task_id: str) -> None:
        """Re-derive ``decision.json`` from the ledger — the authoritative record wins over any clobber.

        The ``record_decision`` tool mirrors the decision mid-beat, but the model can still ``write_file``
        a divergent ``decision.json`` afterward. At landing we overwrite it with the recorded row so the
        landed mirror, the ledger, and the ``sources.json`` packet all agree. No-op without a ledger, or
        when nothing was recorded (an ungrounded plan the DoD floor would already have blocked).
        """
        if self._ledger is None:
            return
        decisions = self._ledger.decisions.for_task(task_id)
        if not decisions:
            return
        record = decisions[-1]  # the most recent recorded decision for this task
        claims = self._ledger.claims.for_decisions([record.id])
        payload = render_decision_mirror(record, claims)
        (worktree / DECISION_MIRROR_DOC).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _write_packet(self, worktree: Path, task_id: str) -> bool:
        """Render the §10 decision packet into the worktree; ``False`` when no ledger is bound."""
        if self._ledger is None:
            return False
        packet = render_packet(self._ledger, task_id)
        (worktree / _PACKET_DOC).write_text(json.dumps(packet, indent=2), encoding="utf-8")
        return True


def pm_lander(company_root: Path, ledger: Ledger | None = None) -> PmLander:
    """The PM's :class:`~chorus.outcomes.OutcomeLander`, rooted at the org workspace.

    When a ``ledger`` is supplied it also renders the §10 decision packet (``sources.json``) from the
    recorded rows; without one the plan still lands and the packet is skipped.
    """
    return PmLander(company_root, ledger)


__all__ = ["PmLander", "pm_lander"]
