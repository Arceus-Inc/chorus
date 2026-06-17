"""DreamObserverBridge — translate dream's event stream into chorus ``Event``s (spec 05 §4, spec 08 §2).

chorus passes ``event_bus.emit`` (a ``Callable[[Event], None]``); dream's ``run_task`` calls
``on_event(dict)``. This bridge sits between them so chorus *witnesses* dream's typed ``role.*``
stream instead of parsing prose. Kinds without a chorus ``run.*`` equivalent are dropped — the closed
vocabulary stays closed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from chorus.events import Event, EventKind

# dream's observer emits plain dicts with a stable ``"kind"``; chorus witnesses the liveness subset
# that maps 1:1 onto its closed ``run.*`` vocabulary. Macro lifecycle kinds (planner/sprint/contract)
# have no chorus equivalent yet and are skipped rather than mislabelled.
_DREAM_TO_CHORUS_KIND: dict[str, EventKind] = {
    "task.started": EventKind.RUN_STARTED,
    "task.completed": EventKind.RUN_DONE,
    "role.text": EventKind.RUN_TEXT,
    "role.tool.start": EventKind.RUN_TOOL_USE,
    "role.tool.result": EventKind.RUN_TOOL_RESULT,
    "evaluator.completed": EventKind.RUN_EVALUATED,
}


class DreamObserverBridge:
    """Adapt a chorus ``emit`` callable to dream's ``on_event(dict)`` observer (spec 05 §4)."""

    def __init__(
        self, emit: Callable[[Event], None], *, task_id: str, clock: Callable[[], datetime]
    ) -> None:
        self._emit = emit
        self._task_id = task_id
        self._clock = clock

    def on_event(self, event: dict[str, Any]) -> None:
        kind = _DREAM_TO_CHORUS_KIND.get(str(event.get("kind", "")))
        if kind is None:
            return
        payload: dict[str, Any] = {k: v for k, v in event.items() if k != "kind"}
        payload["dream_kind"] = event.get("kind")
        self._emit(Event(kind=kind, at=self._clock(), task_id=self._task_id, payload=payload))


__all__ = ["DreamObserverBridge"]
