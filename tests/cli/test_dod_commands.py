"""The console's `dod set` verb — attach a typed Definition of Done to a task (spec 04 §1)."""

from __future__ import annotations

import io

import pytest

from chorus.ledger import SqliteLedger, Task
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration


def _run(line: str, ledger: SqliteLedger) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    dispatch(line, session=CliSession(ledger=ledger), console=Console(out=buffer, colour=False),
             registry=REGISTRY)
    return LoopSignal.CONTINUE, buffer.getvalue()


def _task(ledger: SqliteLedger) -> None:
    ledger.tasks.submit(Task(id="t1", intent="ship"))


def test_set_command_dod(ledger: SqliteLedger) -> None:
    _task(ledger)
    _, out = _run("dod set t1 command pytest -q && ruff check .", ledger)
    assert "command" in out and "t1" in out
    verifier = ledger.dod.verifier_for_task("t1")
    assert verifier is not None and verifier.kind.value == "command"
    assert verifier.spec.command == "pytest -q && ruff check ."  # type: ignore[union-attr]


def test_set_human_approval_dod(ledger: SqliteLedger) -> None:
    _task(ledger)
    _, out = _run("dod set t1 human_approval board", ledger)
    assert "human_approval" in out
    verifier = ledger.dod.verifier_for_task("t1")
    assert verifier is not None and verifier.kind.value == "human_approval"


def test_set_agent_review_dod(ledger: SqliteLedger) -> None:
    _task(ledger)
    _run("dod set t1 agent_review reviewer be strict", ledger)
    verifier = ledger.dod.verifier_for_task("t1")
    assert verifier is not None and verifier.kind.value == "agent_review"
    assert verifier.spec.reviewer_role == "reviewer"  # type: ignore[union-attr]


def test_set_on_unknown_task_errors(ledger: SqliteLedger) -> None:
    _, out = _run("dod set ghost command pytest -q", ledger)
    assert "error:" in out and "ghost" in out


def test_set_bad_kind_errors(ledger: SqliteLedger) -> None:
    _task(ledger)
    _, out = _run("dod set t1 vibes", ledger)
    assert "error:" in out and "vibes" in out


def test_set_command_without_a_command_errors(ledger: SqliteLedger) -> None:
    _task(ledger)
    _, out = _run("dod set t1 command", ledger)
    assert "error:" in out


def test_set_twice_errors_cleanly(ledger: SqliteLedger) -> None:
    _task(ledger)
    _run("dod set t1 command pytest -q", ledger)
    _, out = _run("dod set t1 command ruff check .", ledger)
    assert "error:" in out and "already" in out


def test_wrong_arity_reports_usage(ledger: SqliteLedger) -> None:
    _, out = _run("dod set t1", ledger)
    assert "usage: dod set" in out


def test_unknown_subcommand_errors(ledger: SqliteLedger) -> None:
    _, out = _run("dod frobnicate", ledger)
    assert "error:" in out
