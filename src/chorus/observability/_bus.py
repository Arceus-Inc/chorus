"""The in-process event bus + durable event log (spec 08 §1).

Every meaningful transition is published here and appended to ``events.jsonl``.
The bus is the one thing the inspector, the audit trail, and (in Arceus) the
realtime board consume. It is **in-process** — the SDK ships no WebSocket
fan-out; Arceus layers that on top (spec 08 §7). The log *rotates* (it is derived
telemetry); the ``activity`` audit table does not (spec 08 §5).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from chorus.events import Event

# A synchronous subscriber callback (the beat observer passes ``emit`` to dream).
Subscriber = Callable[[Event], None]


class EventBus:
    """Publish/subscribe over the typed :class:`Event` envelope (spec 08 §1).

    The beat passes :meth:`emit` to ``dream.run_task(observer=...)`` so dream's
    structured engine events (``run.*``) are witnessed verbatim — chorus never
    parses prose to learn a tool call or a verdict (spec 08 §2).
    """

    def __init__(self, *, log_path: str | None = None) -> None:
        self.log_path = log_path

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Register a subscriber; returns an unsubscribe handle."""
        raise NotImplementedError("spec 08 §1: in-process fan-out")

    def emit(self, event: Event) -> None:
        """Publish to subscribers and append to the durable log."""
        raise NotImplementedError("spec 08 §1: fan-out + append to events.jsonl")

    def replay(self, *, after: str | None = None) -> Iterator[Event]:
        """Read the event log from the active (and, on demand, sealed) segments."""
        raise NotImplementedError("spec 08 §1/§5: read active + sealed segments")


__all__ = [
    "EventBus",
    "Subscriber",
]
