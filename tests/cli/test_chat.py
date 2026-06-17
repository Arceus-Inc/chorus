"""Tests for the conversational ``chat`` sub-loop (chorus_cli._chat).

Three layers, all dream-free: the :class:`ChatRenderBus` rendering from synthetic events, the
``ensure_task`` auto-promote decision against a real in-memory ledger, and the full ``run_chat`` loop
driven through a real :class:`Scheduler` wired with a fake beat runner that emits a scripted event
stream. The real-provider path stays manual (like ``tick`` / ``examples/real_beat.py``).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from chorus.events import Event, EventKind
from chorus.heartbeat import BeatOutcome, Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli import Console
from chorus_cli._chat import ChatBeatService, ChatRenderBus, ensure_task, run_chat

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)


# -- ChatRenderBus (unit) ---------------------------------------------------------------------------


def _bus() -> tuple[ChatRenderBus, io.StringIO]:
    out = io.StringIO()
    return ChatRenderBus(out, colour=False), out


def _text(task_id: str, text: str) -> Event:
    return Event(kind=EventKind.RUN_TEXT, at=_NOW, task_id=task_id, payload={"text": text})


def test_render_bus_streams_text_verbatim() -> None:
    bus, out = _bus()
    bus.emit(_text("t1", "hello "))
    bus.emit(_text("t1", "world"))
    assert out.getvalue() == "hello world"


def test_render_bus_renders_tool_use_and_result_on_their_own_lines() -> None:
    bus, out = _bus()
    bus.emit(_text("t1", "let me check"))  # mid-line prose
    bus.emit(Event(kind=EventKind.RUN_TOOL_USE, at=_NOW, payload={"tool": "read_file"}))
    bus.emit(
        Event(kind=EventKind.RUN_TOOL_RESULT, at=_NOW, payload={"tool": "read_file", "is_error": False})
    )
    bus.emit(
        Event(kind=EventKind.RUN_TOOL_RESULT, at=_NOW, payload={"tool": "bash", "is_error": True})
    )
    lines = out.getvalue().splitlines()
    # the half-written prose line is broken before the first structured line
    assert lines[0] == "let me check"
    assert "[tool read_file]" in lines[1]
    assert "[-> read_file ok]" in lines[2]
    assert "[-> bash error]" in lines[3]


def test_render_bus_is_silent_for_lifecycle_kinds() -> None:
    bus, out = _bus()
    bus.emit(Event(kind=EventKind.RUN_STARTED, at=_NOW, payload={}))
    bus.emit(Event(kind=EventKind.RUN_DONE, at=_NOW, payload={}))
    assert out.getvalue() == ""


def test_render_bus_end_turn_closes_a_half_written_line() -> None:
    bus, out = _bus()
    bus.emit(_text("t1", "no trailing newline"))
    bus.end_turn()
    assert out.getvalue() == "no trailing newline\n"


# -- ensure_task (auto-promote) ---------------------------------------------------------------------


def test_ensure_task_promotes_a_fresh_task_when_none_is_workable(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="e1", name="a", role="engineer"))
    task_id, mode = ensure_task(ledger, "e1", "ship the thing")
    assert mode == "promote"
    task = ledger.tasks.get(task_id)
    assert task is not None
    assert task.intent == "ship the thing"
    assert task.assignee_employee_id == "e1"
    assert task.status is TaskStatus.TODO  # assign moved backlog -> todo
    # the line is recorded as a message linked to the task
    inbox = ledger.messages.inbox("e1")
    assert len(inbox) == 1
    assert inbox[0].body == "ship the thing"
    assert inbox[0].task_id == task_id
    # exactly the task-assigned wake is queued (no competing message wake)
    queued = ledger.wakes.queued()
    assert [w.payload.get("task_id") for w in queued] == [task_id]


def test_ensure_task_attaches_to_a_workable_task(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="e1", name="a", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="original", status=TaskStatus.TODO, assignee_employee_id="e1"))
    task_id, mode = ensure_task(ledger, "e1", "actually, do it this way")
    assert mode == "attach"
    assert task_id == "t1"
    # a recovery (steer) wake is enqueued for the live task
    queued = ledger.wakes.queued()
    assert len(queued) == 1
    assert queued[0].payload["task_id"] == "t1"
    assert queued[0].payload.get("cause") == "chat_steer"


def test_ensure_task_does_not_double_wake_the_same_task(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="e1", name="a", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="x", status=TaskStatus.TODO, assignee_employee_id="e1"))
    ensure_task(ledger, "e1", "first steer")
    ensure_task(ledger, "e1", "second steer")
    # both lines recorded, but only one wake queued for the task
    assert len(ledger.messages.inbox("e1")) == 2
    assert len(ledger.wakes.queued()) == 1


# -- run_chat (full loop, fake beat runner) ---------------------------------------------------------


class _FakeChatBeat:
    """A :class:`BeatRunner` that streams a scripted event sequence then returns a verdict."""

    def __init__(self, *, passed: bool = True, cost_cents: int = 7) -> None:
        self._passed = passed
        self._cost_cents = cost_cents
        self.calls: list[str] = []

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        observer: Callable[[Event], None] | None = None,
    ) -> BeatOutcome:
        self.calls.append(intent)
        if observer is not None:
            emit = observer
            emit(Event(kind=EventKind.RUN_TEXT, at=_NOW, task_id=task_id, payload={"text": f"on it: {intent}"}))
            emit(Event(kind=EventKind.RUN_TOOL_USE, at=_NOW, task_id=task_id, payload={"tool": "read_file"}))
            emit(
                Event(
                    kind=EventKind.RUN_TOOL_RESULT,
                    at=_NOW,
                    task_id=task_id,
                    payload={"tool": "read_file", "is_error": False},
                )
            )
        return BeatOutcome(
            passed=self._passed,
            outcome={"steps_total": 1, "steps_done": 1 if self._passed else 0},
            summary="done",
            cost_cents=self._cost_cents,
            model="gpt-test",
            input_tokens=10,
            output_tokens=20,
        )


def _chat_harness(
    ledger: SqliteLedger, beat: _FakeChatBeat
) -> tuple[ChatBeatService, ChatRenderBus, Console, io.StringIO]:
    out = io.StringIO()
    render_bus = ChatRenderBus(out, colour=False)
    console = Console(out=out, colour=False)
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=beat,  # type: ignore[arg-type]  # structural BeatRunner
        event_bus=render_bus,
        max_concurrent_runs=1,
    )
    service = ChatBeatService(scheduler, model="gpt-test", working_dir="/tmp/chat")
    return service, render_bus, console, out


def test_run_chat_runs_a_turn_streams_the_reply_and_lands_the_task(
    ledger: SqliteLedger, make_input
) -> None:
    ledger.employees.create(Employee(id="e1", name="alice", role="engineer"))
    beat = _FakeChatBeat()
    service, render_bus, console, out = _chat_harness(ledger, beat)

    run_chat(
        "e1",
        ledger=ledger,
        service=service,
        render_bus=render_bus,
        console=console,
        input_func=make_input(["build the parser", "/quit"]),
    )

    text = out.getvalue()
    # the beat ran for the typed line
    assert beat.calls == ["build the parser"]
    # the reply streamed, with tool lines
    assert "on it: build the parser" in text
    assert "[tool read_file]" in text
    assert "[-> read_file ok]" in text
    # verdict footer: task landed done, this turn's spend shown
    assert "status=done" in text
    assert "cost=7c" in text
    # the task actually landed in the ledger
    tasks_done = [t for t in [ledger.tasks.get(tid) for tid in _all_task_ids(ledger)] if t]
    assert any(t.intent == "build the parser" and t.status is TaskStatus.DONE for t in tasks_done)


def test_run_chat_quits_on_eof(ledger: SqliteLedger, make_input) -> None:
    ledger.employees.create(Employee(id="e1", name="alice", role="engineer"))
    beat = _FakeChatBeat()
    service, render_bus, console, _out = _chat_harness(ledger, beat)
    # no lines at all → immediate EOF → clean return, no beat
    run_chat(
        "e1",
        ledger=ledger,
        service=service,
        render_bus=render_bus,
        console=console,
        input_func=make_input([]),
    )
    assert beat.calls == []


def test_run_chat_slash_quit_leaves_without_running_a_beat(ledger: SqliteLedger, make_input) -> None:
    ledger.employees.create(Employee(id="e1", name="alice", role="engineer"))
    beat = _FakeChatBeat()
    service, render_bus, console, out = _chat_harness(ledger, beat)
    run_chat(
        "e1",
        ledger=ledger,
        service=service,
        render_bus=render_bus,
        console=console,
        input_func=make_input(["/help", "/quit", "build something"]),
    )
    assert beat.calls == []  # /quit left before the third line
    assert "chat commands:" in out.getvalue()


def _all_task_ids(ledger: SqliteLedger) -> list[str]:
    """Every task id (test helper — the chat creates ids we don't know up front)."""
    rows = ledger.tasks._conn.execute("SELECT id FROM task").fetchall()
    return [r["id"] for r in rows]
