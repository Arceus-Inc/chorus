"""The console's approval verbs — open / list / approve / deny over the resolver (spec 04 §5)."""

from __future__ import annotations

import io
from datetime import datetime

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.workforce import Employee
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


def _session(ledger: SqliteLedger) -> CliSession:
    return CliSession(ledger=ledger, clock=lambda: _NOW, company_id="acme")


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    dispatch(line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY)
    return LoopSignal.CONTINUE, buffer.getvalue()


def _task(ledger: SqliteLedger, task_id: str = "t1") -> None:
    ledger.employees.create(Employee(id="alice", name="Alice", role="engineer"))
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.IN_PROGRESS, assignee_employee_id="alice")
    )


# -- open + list ------------------------------------------------------------------------------------


def test_open_parks_the_task_and_lists_it(ledger: SqliteLedger) -> None:
    _task(ledger)
    session = _session(ledger)
    _, out = _run("approval open t1 acceptance sign off the spec", session)
    assert "opened ap" in out and "blocked" in out
    assert ledger.tasks.get("t1").status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    _, listed = _run("approvals", session)  # alias
    assert "t1" in listed and "acceptance" in listed


def test_list_empty(ledger: SqliteLedger) -> None:
    _, out = _run("approval", _session(ledger))
    assert "(none)" in out


def test_open_bad_gate_errors(ledger: SqliteLedger) -> None:
    _task(ledger)
    _, out = _run("approval open t1 maybe reason", _session(ledger))
    assert "error:" in out and "maybe" in out


def test_open_unknown_task_errors(ledger: SqliteLedger) -> None:
    _, out = _run("approval open ghost acceptance reason", _session(ledger))
    assert "error:" in out and "ghost" in out


def test_open_wrong_arity_reports_usage(ledger: SqliteLedger) -> None:
    _task(ledger)
    _, out = _run("approval open t1 acceptance", _session(ledger))  # no reason
    assert "usage: approval open" in out


def test_open_twice_errors_cleanly(ledger: SqliteLedger) -> None:
    _task(ledger)
    session = _session(ledger)
    _run("approval open t1 acceptance first", session)
    _, out = _run("approval open t1 acceptance second", session)
    assert "error:" in out and "already" in out


# -- approve / deny ---------------------------------------------------------------------------------


def test_acceptance_approve_marks_done(ledger: SqliteLedger) -> None:
    _task(ledger)
    session = _session(ledger)
    _run("approval open t1 acceptance sign off", session)
    approval_id = ledger.approvals.pending()[0].id
    _, out = _run(f"approval approve {approval_id}", session)
    assert "approved" in out and "done" in out
    assert ledger.tasks.get("t1").status is TaskStatus.DONE  # type: ignore[union-attr]


def test_authorization_approve_unblocks_to_todo(ledger: SqliteLedger) -> None:
    _task(ledger)
    session = _session(ledger)
    _run("approval open t1 authorization board sign-off", session)
    approval_id = ledger.approvals.pending()[0].id
    _, out = _run(f"approval approve {approval_id}", session)
    assert "todo" in out
    assert ledger.tasks.get("t1").status is TaskStatus.TODO  # type: ignore[union-attr]


def test_deny_authorization_cancels(ledger: SqliteLedger) -> None:
    _task(ledger)
    session = _session(ledger)
    _run("approval open t1 authorization x", session)
    approval_id = ledger.approvals.pending()[0].id
    _, out = _run(f"approval deny {approval_id}", session)
    assert "denied" in out and "cancelled" in out
    assert ledger.tasks.get("t1").status is TaskStatus.CANCELLED  # type: ignore[union-attr]


def test_approve_unknown_errors(ledger: SqliteLedger) -> None:
    _, out = _run("approval approve ghost", _session(ledger))
    assert "error:" in out and "ghost" in out


def test_approve_already_decided_errors(ledger: SqliteLedger) -> None:
    _task(ledger)
    session = _session(ledger)
    _run("approval open t1 authorization x", session)
    approval_id = ledger.approvals.pending()[0].id
    _run(f"approval approve {approval_id}", session)
    _, out = _run(f"approval approve {approval_id}", session)
    assert "error:" in out and "already" in out


def test_approve_wrong_arity_reports_usage(ledger: SqliteLedger) -> None:
    _, out = _run("approval approve", _session(ledger))
    assert "usage: approval approve" in out


def test_unknown_subcommand_errors(ledger: SqliteLedger) -> None:
    _, out = _run("approval frobnicate", _session(ledger))
    assert "error:" in out and "frobnicate" in out
