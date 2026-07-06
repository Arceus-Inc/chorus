"""The read-eval loop and one-line dispatch — driven with scripted input, no stdin."""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest

from chorus.ledger import SqliteLedger
from chorus_cli import (
    CliSession,
    CommandContext,
    CommandRegistry,
    Console,
    LoopSignal,
    dispatch,
    run_repl,
)
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration

MakeInput = Callable[[list[str]], Callable[[str], str]]


# -- dispatch ---------------------------------------------------------------------------------------


def _dispatch(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    signal = dispatch(
        line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY
    )
    return signal, buffer.getvalue()


def test_blank_line_is_a_noop(session: CliSession) -> None:
    signal, out = _dispatch("   ", session)
    assert signal is LoopSignal.CONTINUE and out == ""


def test_unknown_verb_is_reported_not_fatal(session: CliSession) -> None:
    signal, out = _dispatch("frobnicate x", session)
    assert signal is LoopSignal.CONTINUE
    assert "unknown command" in out and "frobnicate" in out


def test_unbalanced_quotes_are_reported_not_fatal(session: CliSession) -> None:
    signal, out = _dispatch('submit t1 "unterminated', session)
    assert signal is LoopSignal.CONTINUE and "error:" in out


def test_quoting_keeps_multiword_arguments_together(
    session: CliSession, ledger: SqliteLedger
) -> None:
    _dispatch('submit t1 "ship the docs"', session)
    task = ledger.tasks.get("t1")
    assert task is not None and task.intent == "ship the docs"


def test_a_handler_error_is_reported_not_fatal(session: CliSession) -> None:
    registry = CommandRegistry()

    @registry.command("boom", summary="raises", usage="boom")
    def _boom(ctx: CommandContext) -> LoopSignal:
        raise RuntimeError("kaboom")

    buffer = io.StringIO()
    signal = dispatch(
        "boom", session=session, console=Console(out=buffer, colour=False), registry=registry
    )
    assert signal is LoopSignal.CONTINUE  # the loop survives a crashing command
    assert "error:" in buffer.getvalue() and "kaboom" in buffer.getvalue()


# -- the loop ---------------------------------------------------------------------------------------


def test_run_repl_quits_on_quit_command(session: CliSession, make_input: MakeInput) -> None:
    out = io.StringIO()
    code = run_repl(session, REGISTRY, input_func=make_input(["quit"]), output=out, colour=False)
    assert code == 0
    assert "chorus console" in out.getvalue()  # the banner printed


def test_run_repl_exits_cleanly_on_eof(session: CliSession, make_input: MakeInput) -> None:
    out = io.StringIO()
    code = run_repl(session, REGISTRY, input_func=make_input([]), output=out, colour=False)
    assert code == 0


def test_run_repl_runs_commands_until_quit(
    session: CliSession, ledger: SqliteLedger, make_input: MakeInput
) -> None:
    out = io.StringIO()
    run_repl(
        session,
        REGISTRY,
        input_func=make_input(["hire Alice engineer", "submit t1 ship", "quit"]),
        output=out,
        colour=False,
    )
    assert ledger.employees.get("alice") is not None
    assert ledger.tasks.get("t1") is not None


def test_run_repl_keeps_going_after_a_bad_command(
    session: CliSession, ledger: SqliteLedger, make_input: MakeInput
) -> None:
    out = io.StringIO()
    run_repl(
        session,
        REGISTRY,
        input_func=make_input(["nonsense", "hire Alice engineer", "quit"]),
        output=out,
        colour=False,
    )
    assert "unknown command" in out.getvalue()
    assert ledger.employees.get("alice") is not None  # loop survived the bad line
