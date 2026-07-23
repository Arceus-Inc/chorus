"""Every console command, driven against a real in-memory ledger.

Each test dispatches one line and asserts both the rendered output and the durable ledger side
effect — these are the integration tests proving the console exposes working chorus functionality.
"""

from __future__ import annotations

import io
from datetime import datetime

import pytest

from chorus.heartbeat import TickReport
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.outcomes import DoDKind, Verifier
from chorus.testing import uid
from chorus.workforce import Employee
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    signal = dispatch(
        line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY
    )
    return signal, buffer.getvalue()


class _FakeBeatService:
    """A stand-in :class:`~chorus_cli.BeatService` — no dream, returns a canned report."""

    def __init__(self, report: TickReport) -> None:
        self._report = report
        self.ticks = 0

    @property
    def model(self) -> str:
        return "fake-deployment"

    def run_tick(self) -> TickReport:
        self.ticks += 1
        return self._report


# -- meta -------------------------------------------------------------------------------------------


def test_help_lists_commands(session: CliSession) -> None:
    _, out = _run("help", session)
    assert "hire" in out and "submit" in out and "assign" in out


def test_help_for_one_command_shows_usage(session: CliSession) -> None:
    _, out = _run("help submit", session)
    assert "submit [--priority=LEVEL] <id> <intent...>" in out


def test_help_for_unknown_command_errors(session: CliSession) -> None:
    _, out = _run("help nope", session)
    assert "error:" in out and "nope" in out


def test_quit_returns_quit_signal(session: CliSession) -> None:
    signal, _ = _run("quit", session)
    assert signal is LoopSignal.QUIT


def test_exit_alias_returns_quit_signal(session: CliSession) -> None:
    signal, _ = _run("exit", session)
    assert signal is LoopSignal.QUIT


# -- workforce --------------------------------------------------------------------------------------


def test_employee_shows_a_record(session: CliSession) -> None:
    _run("hire Alice engineer", session)
    _, out = _run("employee alice", session)
    assert "alice" in out and "engineer" in out


def test_employee_unknown_errors(session: CliSession) -> None:
    _, out = _run(f"employee {uid('ghost')}", session)
    assert "error:" in out and uid("ghost") in out


def test_employee_wrong_arity_reports_usage(session: CliSession) -> None:
    _, out = _run("employee", session)
    assert "usage: employee" in out


# -- tasks ------------------------------------------------------------------------------------------


def test_submit_creates_a_backlog_task(session: CliSession, ledger: Ledger) -> None:
    _, out = _run(f"submit {uid('t1')} ship the docs", session)
    assert f"submitted {uid('t1')}" in out
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.intent == "ship the docs"
    assert task.status is TaskStatus.BACKLOG


def test_submit_with_priority_flag(session: CliSession, ledger: Ledger) -> None:
    _run(f"submit {uid('t1')} --priority=high ship it", session)
    task = ledger.tasks.get(uid("t1"))
    assert task is not None and task.priority.value == "high" and task.intent == "ship it"


def test_submit_priority_space_separated(session: CliSession, ledger: Ledger) -> None:
    _run(f"submit {uid('t1')} --priority high ship it", session)
    task = ledger.tasks.get(uid("t1"))
    assert task is not None and task.priority.value == "high" and task.intent == "ship it"


def test_submit_with_bad_priority_errors_and_writes_nothing(
    session: CliSession, ledger: Ledger
) -> None:
    _, out = _run(f"submit {uid('t1')} --priority=urgent do it", session)
    assert "error:" in out and "urgent" in out
    assert ledger.tasks.get(uid("t1")) is None


def test_submit_missing_intent_reports_usage(session: CliSession, ledger: Ledger) -> None:
    _, out = _run(f"submit {uid('t1')}", session)
    assert "usage: submit" in out
    assert ledger.tasks.get(uid("t1")) is None


def test_submit_duplicate_id_errors_cleanly(session: CliSession) -> None:
    _run(f"submit {uid('t1')} ship it", session)
    _, out = _run(f"submit {uid('t1')} ship it again", session)
    assert "error:" in out and "already exists" in out and uid("t1") in out


def test_task_shows_task_runs_and_dod(session: CliSession, ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship"))
    _, out = _run(f"task {uid('t1')}", session)
    assert uid("t1") in out and "ship" in out and "runs:" in out


def test_task_unknown_errors(session: CliSession) -> None:
    _, out = _run(f"task {uid('ghost')}", session)
    assert "error:" in out


def test_task_shows_its_dod_when_present(session: CliSession, ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship"))
    ledger.dod.create(uid("t1"), Verifier.command("pytest -q"))
    _, out = _run(f"task {uid('t1')}", session)
    assert "dod:" in out and "command" in out


def test_assign_moves_backlog_to_todo_and_wakes(session: CliSession, ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="Alice", role="engineer"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship"))
    _, out = _run(f"assign {uid('t1')} alice", session)
    assert f"assigned {uid('t1')}" in out and "woke" in out
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.TODO
    assert any(w.employee_id == "alice" for w in ledger.wakes.queued())


def test_assign_unknown_task_errors(session: CliSession, ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="Alice", role="engineer"))
    _, out = _run(f"assign {uid('ghost')} alice", session)  # employee exists, task does not
    assert "error:" in out and uid("ghost") in out


def test_assign_unknown_employee_errors_cleanly(session: CliSession, ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship"))
    _, out = _run(f"assign t1 {uid('ghost')}", session)
    assert "error:" in out and uid("ghost") in out
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.BACKLOG  # not left half-assigned


def test_eligible_lists_assigned_unblocked_tasks(session: CliSession, ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="Alice", role="engineer"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship the thing"))
    _run(f"assign {uid('t1')} alice", session)
    _, out = _run("eligible", session)
    assert uid("t1") in out


def test_eligible_bad_limit_errors(session: CliSession) -> None:
    _, out = _run("eligible zero", session)
    assert "error:" in out


def test_eligible_zero_limit_errors(session: CliSession) -> None:
    _, out = _run("eligible 0", session)
    assert "error:" in out and "positive" in out


def test_eligible_honours_a_valid_limit(session: CliSession) -> None:
    signal, out = _run("eligible 5", session)
    assert signal is LoopSignal.CONTINUE and "(none)" in out  # empty backlog, no error


def test_task_wrong_arity_reports_usage(session: CliSession) -> None:
    _, out = _run("task", session)
    assert "usage: task" in out


def test_assign_wrong_arity_reports_usage(session: CliSession) -> None:
    _, out = _run(f"assign {uid('t1')}", session)
    assert "usage: assign" in out


# -- coordination -----------------------------------------------------------------------------------


def test_wakes_empty_prints_placeholder(session: CliSession) -> None:
    _, out = _run("wakes", session)
    assert "(none)" in out


def test_wakes_lists_queued(session: CliSession, ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="Alice", role="engineer"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship"))
    _run(f"assign {uid('t1')} alice", session)
    _, out = _run("wakes", session)
    assert "alice" in out and "task_assigned" in out


def test_message_delivers_and_shows_in_inbox(session: CliSession, ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="Alice", role="engineer"))
    _, out = _run("message alice please review the PR", session)
    assert "delivered to alice" in out
    inbox = ledger.messages.inbox("alice")
    assert len(inbox) == 1 and inbox[0].body == "please review the PR"


def test_message_missing_body_reports_usage(session: CliSession) -> None:
    _, out = _run("message alice", session)
    assert "usage: message" in out


def test_message_to_unknown_employee_errors_cleanly(session: CliSession) -> None:
    _, out = _run(f"message {uid('ghost')} hello there", session)
    assert "error:" in out and uid("ghost") in out


def test_inbox_shows_delivered_messages(session: CliSession) -> None:
    _run("hire Alice engineer", session)
    _run("message alice hello there", session)
    _, out = _run("inbox alice", session)
    assert "hello there" in out


# -- accounting -------------------------------------------------------------------------------------


def test_inbox_wrong_arity_reports_usage(session: CliSession) -> None:
    _, out = _run("inbox", session)
    assert "usage: inbox" in out


def test_cost_reports_zero_for_a_fresh_employee(session: CliSession) -> None:
    _run("hire Alice engineer", session)
    _, out = _run("cost alice", session)
    assert "alice has spent 0 cents" in out


def test_cost_wrong_arity_reports_usage(session: CliSession) -> None:
    _, out = _run("cost", session)
    assert "usage: cost" in out


def test_schema_prints_a_version(session: CliSession) -> None:
    _, out = _run("schema", session)
    assert "schema version:" in out


# -- tick -------------------------------------------------------------------------------------------


def test_tick_without_a_beat_service_explains_how_to_enable_it(session: CliSession) -> None:
    _, out = _run("tick", session)
    assert "error:" in out and "AZURE_OPENAI_API_KEY" in out


def test_tick_runs_the_kernel_and_reports(ledger: Ledger) -> None:
    report = TickReport(
        at=datetime.fromisoformat("2026-06-16T12:00:00+00:00"), wakes_dispatched=1, beats_started=1
    )
    beats = _FakeBeatService(report)
    session = CliSession(ledger=ledger, beats=beats)
    signal, out = _run("tick", session)
    assert signal is LoopSignal.CONTINUE
    assert beats.ticks == 1
    assert "fake-deployment" in out  # announces the model
    assert "beats_started" in out and "1" in out
    assert "task <id>" in out  # points the user at the result


def test_tick_in_minimal_mode_defers_to_background_heartbeat(ledger: Ledger) -> None:
    report = TickReport(at=datetime.fromisoformat("2026-06-16T12:00:00+00:00"), beats_started=1)
    beats = _FakeBeatService(report)
    session = CliSession(ledger=ledger, beats=beats, minimal_mode=True)

    _, out = _run("tick", session)

    assert beats.ticks == 0
    assert "heartbeat is already live" in out


def test_minimal_assign_task_uses_file_exists_dod(ledger: Ledger) -> None:
    session = CliSession(ledger=ledger, minimal_mode=True)

    _, out = _run(
        "assign-task employee get the total number of md files in the dir and write it to total_md_files.md",
        session,
    )

    assert "assigned" in out
    task = ledger.tasks.open_for_assignee("employee")
    assert task is not None
    dod = ledger.dod.get_for_task(task.id)
    assert dod is not None
    verifier = ledger.dod.verifier_for_task(task.id)
    assert verifier is not None
    assert verifier.kind is DoDKind.COMMAND
    steps = verifier.verification_steps()
    assert len(steps) == 1
    assert "total_md_files.md" in steps[0].command
    assert "pytest" not in steps[0].command


def test_tick_with_nothing_to_dispatch_says_so(ledger: Ledger) -> None:
    report = TickReport(at=datetime.fromisoformat("2026-06-16T12:00:00+00:00"))
    session = CliSession(ledger=ledger, beats=_FakeBeatService(report))
    _, out = _run("tick", session)
    assert "nothing to dispatch" in out


def test_tick_reports_a_budget_gated_dispatch(ledger: Ledger) -> None:
    report = TickReport(at=datetime.fromisoformat("2026-06-16T12:00:00+00:00"), budget_gated=1)
    session = CliSession(ledger=ledger, beats=_FakeBeatService(report))
    _, out = _run("tick", session)
    assert "gated by a budget" in out


def test_tick_rejects_arguments(ledger: Ledger) -> None:
    session = CliSession(ledger=ledger, beats=_FakeBeatService(TickReport(at=datetime.now())))
    _, out = _run("tick now", session)
    assert "usage: tick" in out
