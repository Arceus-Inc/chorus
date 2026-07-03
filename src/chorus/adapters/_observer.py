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

# The dream builtin whose start/result frame an intra-beat subagent (dream.swarm). Its ``role.tool.*``
# events are ALSO surfaced as first-class SUBAGENT_* events so a consumer sees the swarm lifecycle
# without pattern-matching tool names.
_SPAWN_TOOL = "spawn_subagent"


class DreamObserverBridge:
    """Adapt a chorus ``emit`` callable to dream's ``on_event(dict)`` observer (spec 05 §4).

    Two normalizations beyond the 1:1 kind map:

    - dream's ``role.tool.result`` carries the tool's text under ``content_preview`` (a bounded
      preview); the bridge mirrors it onto the stable ``content`` key so consumers read one
      vocabulary regardless of tool.
    - ``spawn_subagent`` start/result are additionally emitted as ``SUBAGENT_SPAWNED`` /
      ``SUBAGENT_COMPLETED``. dream's result event has no subagent name (only the tool), so the
      name is correlated from the start's ``input`` via a small FIFO of pending spawns.
    """

    def __init__(
        self, emit: Callable[[Event], None], *, task_id: str, clock: Callable[[], datetime]
    ) -> None:
        self._emit = emit
        self._task_id = task_id
        self._clock = clock
        # spawn_subagent start/result correlate FIFO: dream's result event drops the subagent name,
        # and spawns are bounded + sequential within a beat, so a queue recovers the pairing.
        self._pending_subagents: list[str] = []

    def on_event(self, event: dict[str, Any]) -> None:
        dream_kind = str(event.get("kind", ""))
        kind = _DREAM_TO_CHORUS_KIND.get(dream_kind)
        if kind is None:
            return
        payload: dict[str, Any] = {k: v for k, v in event.items() if k != "kind"}
        payload["dream_kind"] = dream_kind
        # Stable verdict/output key: dream previews tool output under ``content_preview``.
        if kind is EventKind.RUN_TOOL_RESULT and "content" not in payload:
            payload["content"] = payload.get("content_preview", "")
        self._emit(Event(kind=kind, at=self._clock(), task_id=self._task_id, payload=payload))
        self._maybe_emit_subagent(dream_kind, event)

    def _maybe_emit_subagent(self, dream_kind: str, event: dict[str, Any]) -> None:
        """Surface the ``spawn_subagent`` lifecycle as first-class SUBAGENT_* events."""
        if event.get("tool") != _SPAWN_TOOL:
            return
        if dream_kind == "role.tool.start":
            name = str(dict(event.get("input") or {}).get("name", "subagent"))
            self._pending_subagents.append(name)
            self._emit_subagent(
                EventKind.SUBAGENT_SPAWNED,
                {"subagent_name": name, "prompt": dict(event.get("input") or {}).get("prompt", "")},
            )
        elif dream_kind == "role.tool.result":
            name = self._pending_subagents.pop(0) if self._pending_subagents else "subagent"
            self._emit_subagent(
                EventKind.SUBAGENT_COMPLETED,
                {
                    "subagent_name": name,
                    "content": event.get("content_preview", ""),
                    "is_error": bool(event.get("is_error", False)),
                },
            )

    def _emit_subagent(self, kind: EventKind, payload: dict[str, Any]) -> None:
        self._emit(Event(kind=kind, at=self._clock(), task_id=self._task_id, payload=payload))


__all__ = ["DreamObserverBridge"]
