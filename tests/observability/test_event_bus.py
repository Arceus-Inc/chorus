"""Spec 08 event spine: durable JSONL log plus in-process fanout."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from chorus.events import Event, EventKind
from chorus.observability import EventBus, FanoutBus

pytestmark = pytest.mark.unit


def _event(kind: EventKind = EventKind.RUN_STARTED) -> Event:
    return Event(
        kind=kind,
        at=datetime(2026, 6, 17, 18, 0, tzinfo=UTC),
        task_id="task_1",
        employee_id="employee",
        run_id="run_1",
        payload={"phase": "demo"},
    )


def test_event_bus_appends_jsonl_and_replays_events(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "events.jsonl"
    bus = EventBus(log_path=path)

    bus.emit(_event())

    raw = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert raw == [
        {
            "at": "2026-06-17T18:00:00+00:00",
            "employee_id": "employee",
            "kind": "run.started",
            "payload": {"phase": "demo"},
            "run_id": "run_1",
            "task_id": "task_1",
            "trace_id": None,
        }
    ]
    assert list(bus.replay()) == [_event()]


def test_event_bus_subscribers_receive_events(tmp_path) -> None:  # type: ignore[no-untyped-def]
    seen: list[Event] = []
    bus = EventBus(log_path=tmp_path / "events.jsonl")
    unsubscribe = bus.subscribe(seen.append)

    bus.emit(_event(EventKind.RUN_DONE))
    unsubscribe()
    bus.emit(_event(EventKind.RUN_STARTED))

    assert seen == [_event(EventKind.RUN_DONE)]


def test_fanout_bus_isolates_sink_failures() -> None:
    seen: list[Event] = []

    class BrokenSink:
        def emit(self, event: Event) -> None:
            raise RuntimeError("sink unavailable")

    class RecordingSink:
        def emit(self, event: Event) -> None:
            seen.append(event)

    event = _event(EventKind.RUN_TOOL_USE)

    FanoutBus(BrokenSink(), RecordingSink()).emit(event)

    assert seen == [event]