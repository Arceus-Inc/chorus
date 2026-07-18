"""Trace stamping — every observed event names its trace and lane (spec 08 §6, CP-1).

``trace_id`` is the ROOT task id of a beat's lineage: the id the product maps to its run, so one
trace threads product run → chorus beats → engine spans. Stamping happens at the scheduler's
observer choke point, so every runner — real or fake — emits stamped events without knowing
about tracing, and an event that already names a field keeps it (the stamper only fills gaps).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from chorus.events import Event

if TYPE_CHECKING:
    from chorus.ledger import Ledger


def trace_root(ledger: Ledger, task_id: str) -> str:
    """The lineage root of ``task_id`` — a root task is its own trace. Cycle-safe."""
    seen: set[str] = set()
    current = task_id
    while current not in seen:
        seen.add(current)
        task = ledger.tasks.get(current)
        if task is None or task.parent_id is None:
            return current
        current = task.parent_id
    return current  # corrupt parent cycle — stop at the repeat rather than loop forever


class TraceStamper:
    """Wrap an ``emit`` callable; fill missing lane fields on every event passing through."""

    def __init__(
        self,
        emit: Callable[[Event], None],
        *,
        trace_id: str,
        task_id: str,
        employee_id: str,
        run_id: str,
    ) -> None:
        self._emit = emit
        self._trace_id = trace_id
        self._task_id = task_id
        self._employee_id = employee_id
        self._run_id = run_id

    def __call__(self, event: Event) -> None:
        self._emit(
            replace(
                event,
                trace_id=event.trace_id or self._trace_id,
                task_id=event.task_id or self._task_id,
                employee_id=event.employee_id or self._employee_id,
                run_id=event.run_id or self._run_id,
            )
        )


__all__ = ["TraceStamper", "trace_root"]
