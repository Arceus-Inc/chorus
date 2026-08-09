"""The console's approval verbs — open / list / approve / deny over the resolver (spec 04 §5)."""

from __future__ import annotations

import io
from datetime import datetime

import pytest

from chorus.ledger import Ledger, Task, TaskStatus
from chorus.testing import uid
from chorus.workforce import Employee
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


def _session(ledger: Ledger) -> CliSession:
    return CliSession(ledger=ledger, clock=lambda: _NOW, company_id="acme")


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    dispatch(line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY)
    return LoopSignal.CONTINUE, buffer.getvalue()


def _task(ledger: Ledger, task_id: str = uid("t1")) -> None:
    ledger.employees.create(Employee(id="alice", name="Alice", role="engineer"))
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.IN_PROGRESS, assignee_employee_id="alice")
    )


# -- open + list ------------------------------------------------------------------------------------


def test_open_parks_the_task_and_lists_it(ledger: Ledger) -> None:
    _task(ledger)
    session = _session(ledger)
    _, out = _run(f"approval open {uid('t1')} acceptance sign off the spec", session)
    assert out.startswith("opened ") and "task blocked" in out
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    _, listed = _run("approvals", session)  # alias
    assert uid("t1") in listed and "acceptance" in listed


def test_list_empty(ledger: Ledger) -> None:
    _, out = _run("approval", _session(ledger))
    assert "(none)" in out


def test_open_bad_gate_errors(ledger: Ledger) -> None:
    _task(ledger)
    _, out = _run(f"approval open {uid('t1')} maybe reason", _session(ledger))
    assert "error:" in out and "maybe" in out


def test_open_unknown_task_errors(ledger: Ledger) -> None:
    _, out = _run(f"approval open {uid('ghost')} acceptance reason", _session(ledger))
    assert "error:" in out and uid("ghost") in out


def test_open_wrong_arity_reports_usage(ledger: Ledger) -> None:
    _task(ledger)
    _, out = _run(f"approval open {uid('t1')} acceptance", _session(ledger))  # no reason
    assert "usage: approval open" in out


def test_open_twice_errors_cleanly(ledger: Ledger) -> None:
    _task(ledger)
    session = _session(ledger)
    _run(f"approval open {uid('t1')} acceptance first", session)
    _, out = _run(f"approval open {uid('t1')} acceptance second", session)
    assert "error:" in out and "already" in out


# -- approve / deny ---------------------------------------------------------------------------------


def test_acceptance_approve_marks_done(ledger: Ledger) -> None:
    _task(ledger)
    session = _session(ledger)
    _run(f"approval open {uid('t1')} acceptance sign off", session)
    approval_id = ledger.approvals.pending()[0].id
    _, out = _run(f"approval approve {approval_id}", session)
    assert "approved" in out and "done" in out
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.DONE  # type: ignore[union-attr]


def test_authorization_approve_cannot_bypass_authenticated_resolution(ledger: Ledger) -> None:
    _task(ledger)
    session = _session(ledger)
    _run(f"approval open {uid('t1')} authorization board sign-off", session)
    approval_id = ledger.approvals.pending()[0].id
    _, out = _run(f"approval approve {approval_id}", session)
    assert "requires authenticated" in out
    task = ledger.tasks.get(uid("t1"))
    assert task is not None and task.status is TaskStatus.BLOCKED


def test_authorization_deny_cannot_bypass_authenticated_resolution(ledger: Ledger) -> None:
    _task(ledger)
    session = _session(ledger)
    _run(f"approval open {uid('t1')} authorization x", session)
    approval_id = ledger.approvals.pending()[0].id
    _, out = _run(f"approval deny {approval_id}", session)
    assert "requires authenticated" in out
    task = ledger.tasks.get(uid("t1"))
    assert task is not None and task.status is TaskStatus.BLOCKED


def test_approve_unknown_errors(ledger: Ledger) -> None:
    _, out = _run(f"approval approve {uid('ghost')}", _session(ledger))
    assert "error:" in out and uid("ghost") in out


def test_approve_already_decided_errors(ledger: Ledger) -> None:
    _task(ledger)
    session = _session(ledger)
    _run(f"approval open {uid('t1')} acceptance x", session)
    approval_id = ledger.approvals.pending()[0].id
    _run(f"approval approve {approval_id}", session)
    _, out = _run(f"approval approve {approval_id}", session)
    assert "error:" in out and "already" in out


def test_approve_wrong_arity_reports_usage(ledger: Ledger) -> None:
    _, out = _run("approval approve", _session(ledger))
    assert "usage: approval approve" in out


def test_unknown_subcommand_errors(ledger: Ledger) -> None:
    _, out = _run("approval frobnicate", _session(ledger))
    assert "error:" in out and "frobnicate" in out
