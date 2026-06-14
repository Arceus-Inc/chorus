"""The inspector — a pure read model over the ledger + event log (spec 08 §3).

Holds no state. Surfaces (Paperclip's layered liveness UI, adapted): the live
beat surface (from the ``run.*`` stream), the liveness vocabulary (straight from
``run.evaluated``), recovery cards (one per open ``recovery_action``), and the
blocked inbox (every stalled task, ranked). The CLI ``chorus inspect`` and (in
Arceus) the web board are both views over this projection.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from chorus.observability._views import TaskView, WorkforceStatus


@runtime_checkable
class Inspector(Protocol):
    """The read-model contract (spec 09 §4) — swappable behind the facade."""

    def status(self) -> WorkforceStatus:
        """The company at a glance — employees, open tasks, runs, incidents."""
        ...

    def task(self, task_id: str) -> TaskView:
        """One task, resolved (names + liveness + blockers)."""
        ...

    def stuck(self) -> list[TaskView]:
        """The blocked inbox — non-terminal tasks with no action-path primitive (spec 08 §2)."""
        ...


class LedgerInspector:
    """The default :class:`Inspector` over the SQLite ledger + event log (spec 08 §3)."""

    def status(self) -> WorkforceStatus:
        raise NotImplementedError("spec 08 §3: project employees/tasks/runs/incidents")

    def task(self, task_id: str) -> TaskView:
        raise NotImplementedError("spec 08 §3: resolve names + derive liveness + blockers")

    def stuck(self) -> list[TaskView]:
        raise NotImplementedError("spec 08 §2: the stuck query (non-terminal, no live path)")


__all__ = [
    "Inspector",
    "LedgerInspector",
]
