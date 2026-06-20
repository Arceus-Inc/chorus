"""``org.dod`` — revise a task's Definition of Done (spec 14 §5.6, spec 04 §1).

A manager tightening applies now; a loosening opens a §5 governance gate. Migrated from the flat
``revise_dod`` verb (spec 14 'migrate all').
"""

from __future__ import annotations

from chorus.ledger import SqliteLedger
from chorus.lifecycle import ReviseOutcome, revise_dod
from chorus.outcomes import Verifier


class DodFacade:
    """The ``org.dod`` surface — revise a task's DoD."""

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def revise(self, task_id: str, new_verifier: Verifier, *, by: str) -> ReviseOutcome:
        """Revise a task's DoD: a manager tighten applies now; a loosen opens a §5 gate (spec 04 §1).

        Raises ``RevisionAuthorityError`` if ``by`` is not the assignee's manager, or ``NoRevision``
        if the task has no DoD / the edit is a no-op."""
        return revise_dod(self._ledger, task_id=task_id, new_verifier=new_verifier, revised_by=by)


__all__ = ["DodFacade"]
