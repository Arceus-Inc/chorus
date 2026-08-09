"""``org.inspect`` — the read-model group (spec 14 §4).

Detailed reads over the ledger + event log. The one-call glance (``org.status()``) stays flat on
``Chorus``; everything finer-grained — one task resolved, the blocked inbox, the event replay, the
manager rollups — lives here. Pure delegation to the :class:`LedgerInspector` and :class:`EventBus`.
"""

from __future__ import annotations

from collections.abc import Iterator

from chorus.events import Event
from chorus.observability import (
    EventBus,
    LedgerInspector,
    OrgObservabilityReport,
    ScrumPacketView,
    TaskThreadView,
    TaskView,
)


class InspectFacade:
    """The ``org.inspect`` surface — task / stuck / events / scrum_packet / org_report."""

    def __init__(self, inspector: LedgerInspector, event_bus: EventBus) -> None:
        self._inspector = inspector
        self._event_bus = event_bus

    def task(self, task_id: str) -> TaskView:
        """One task, resolved (names + liveness + unresolved blockers). ``KeyError`` if unknown."""
        return self._inspector.task(task_id)

    def task_thread(self, task_id: str) -> TaskThreadView:
        """One rooted task subtree with its attached durable rows. ``KeyError`` if unknown."""
        return self._inspector.task_thread(task_id)

    def stuck(self) -> list[TaskView]:
        """The blocked inbox — non-terminal tasks with no action-path primitive (spec 08 §2)."""
        return self._inspector.stuck()

    def events(self, *, after: str | None = None) -> Iterator[Event]:
        """Replay the event stream from ``after`` (exclusive), or from the start."""
        return self._event_bus.replay(after=after)

    def scrum_packet(self, task_id: str) -> ScrumPacketView:
        """Manager packet rollup for one delegated parent task."""
        return self._inspector.scrum_packet(task_id)

    def org_report(self) -> OrgObservabilityReport:
        """Combined manager + leaf observability rollup."""
        return self._inspector.org_report()


__all__ = ["InspectFacade"]
