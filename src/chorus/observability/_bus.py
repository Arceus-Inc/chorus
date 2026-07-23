"""The in-process event bus + durable event log (spec 08 §1).

Every meaningful transition is published here and appended to ``events.jsonl``.
The bus is the one thing the inspector, the audit trail, and (in Arceus) the
realtime board consume. It is **in-process** — the SDK ships no WebSocket
fan-out; Arceus layers that on top (spec 08 §7). The log *rotates* (it is derived
telemetry); the ``activity`` audit table does not (spec 08 §5).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from chorus.events import Event, EventKind

_logger = logging.getLogger("chorus.observability.bus")

# A synchronous subscriber callback (the beat observer passes ``emit`` to dream).
Subscriber = Callable[[Event], None]


@runtime_checkable
class EventSink(Protocol):
    """Anything the scheduler can emit typed events into."""

    def emit(self, event: Event) -> None: ...


class EventBus:
    """Publish/subscribe over the typed :class:`Event` envelope (spec 08 §1).

    The beat passes :meth:`emit` to ``dream.run_task(observer=...)`` so dream's
    structured engine events (``run.*``) are witnessed verbatim — chorus never
    parses prose to learn a tool call or a verdict (spec 08 §2).
    """

    def __init__(self, *, log_path: str | Path | None = None) -> None:
        self.log_path = str(log_path) if log_path is not None else None
        self._subscribers: list[Subscriber] = []

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Register a subscriber; returns an unsubscribe handle."""
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def emit(self, event: Event) -> None:
        """Publish to subscribers and append to the durable log."""
        if self.log_path is not None:
            path = Path(self.log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(_event_to_json(event), sort_keys=True, default=str) + "\n")
        for subscriber in tuple(self._subscribers):
            subscriber(event)

    def replay(self, *, after: str | None = None) -> Iterator[Event]:
        """Read the event log from the active (and, on demand, sealed) segments."""
        if self.log_path is None:
            return
        path = Path(self.log_path)
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = _event_from_json(json.loads(line))
            if after is not None and event.at.isoformat() <= after:
                continue
            yield event


class FanoutBus:
    """Forward each event to multiple sinks, isolating sink failures from the beat."""

    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = sinks

    def emit(self, event: Event) -> None:
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception:
                # Isolate the beat from a bad sink, but never silently — a dead sink that leaves no
                # trace is invisible forever. Log with the traceback and carry on to the next sink.
                _logger.warning("event sink %r failed on %s", sink, event.kind, exc_info=True)


def _event_to_json(event: Event) -> dict[str, object]:
    return {
        "kind": event.kind.value,
        "at": event.at.isoformat(),
        "trace_id": event.trace_id,
        "task_id": event.task_id,
        "employee_id": event.employee_id,
        "run_id": event.run_id,
        "payload": dict(event.payload),
    }


def _event_from_json(data: dict[str, object]) -> Event:
    return Event(
        kind=EventKind(str(data["kind"])),
        at=datetime.fromisoformat(str(data["at"])),
        trace_id=_optional_str(data.get("trace_id")),
        task_id=_optional_str(data.get("task_id")),
        employee_id=_optional_str(data.get("employee_id")),
        run_id=_optional_str(data.get("run_id")),
        payload=_payload(data.get("payload")),
    )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _payload(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


__all__ = [
    "EventBus",
    "EventSink",
    "FanoutBus",
    "Subscriber",
]
