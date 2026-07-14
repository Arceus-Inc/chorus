"""The console's ``routine`` verbs — add / list / show / pause / resume (spec 13 §7, M4 S1).

These drive the verbs end-to-end through ``dispatch`` over a real in-memory ledger; the handlers
route through the ``Chorus`` facade (``add_routine`` etc.), so the CLI and the public API stay one
path. Policy/status arguments are parsed to enums at the boundary — a bad value is a reported error,
never a stringly value slipping through.
"""

from __future__ import annotations

import io

import pytest

from chorus.ledger import RoutineStatus, SqliteLedger
from chorus.workforce import Employee
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration


def _session(ledger: SqliteLedger) -> CliSession:
    return CliSession(ledger=ledger)


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    signal = dispatch(
        line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY
    )
    return signal, buffer.getvalue()


def _with_moe(ledger: SqliteLedger) -> SqliteLedger:
    ledger.employees.create(Employee(id="moe", name="Moe", role="engineer"))
    return ledger


def test_add_creates_a_routine(ledger: SqliteLedger) -> None:
    _with_moe(ledger)
    sig, out = _run('routine add moe weekly review --schedule "0 9 * * 1"', _session(ledger))
    assert sig is LoopSignal.CONTINUE
    routines = ledger.routines.list()
    assert len(routines) == 1
    assert routines[0].employee_id == "moe"
    assert routines[0].intent_template == "weekly review"
    assert routines[0].id in out  # the new routine's id is echoed back
    (trigger,) = ledger.routine_triggers.by_routine(routines[0].id)
    assert trigger.cron_expression == "0 9 * * 1"


def test_add_without_a_schedule_is_a_usage_error(ledger: SqliteLedger) -> None:
    _with_moe(ledger)
    _, out = _run("routine add moe weekly review", _session(ledger))
    assert "usage" in out.lower()
    assert ledger.routines.list() == []


def test_add_for_an_unknown_employee_reports_an_error(ledger: SqliteLedger) -> None:
    _, out = _run('routine add ghost do thing --schedule "0 * * * *"', _session(ledger))
    assert "ghost" in out.lower() or "unknown" in out.lower()
    assert ledger.routines.list() == []


def test_add_with_a_bad_concurrency_is_reported(ledger: SqliteLedger) -> None:
    _with_moe(ledger)
    _, out = _run('routine add moe x --schedule "0 * * * *" --concurrency turbo', _session(ledger))
    assert "concurrency" in out.lower()
    assert ledger.routines.list() == []


def test_list_shows_each_routine(ledger: SqliteLedger) -> None:
    _with_moe(ledger)
    _run('routine add moe weekly review --schedule "0 9 * * 1"', _session(ledger))
    _, out = _run("routine list", _session(ledger))
    rid = ledger.routines.list()[0].id
    assert rid in out
    assert "moe" in out


def test_show_renders_definition_and_trigger(ledger: SqliteLedger) -> None:
    _with_moe(ledger)
    _run('routine add moe weekly review --schedule "0 9 * * 1"', _session(ledger))
    rid = ledger.routines.list()[0].id
    _, out = _run(f"routine show {rid}", _session(ledger))
    assert "0 9 * * 1" in out
    assert "coalesce" in out  # the safe default policy is visible


def test_pause_then_resume_toggles_status(ledger: SqliteLedger) -> None:
    _with_moe(ledger)
    _run('routine add moe x --schedule "0 * * * *"', _session(ledger))
    rid = ledger.routines.list()[0].id

    _run(f"routine pause {rid}", _session(ledger))
    assert ledger.routines.get(rid).status is RoutineStatus.PAUSED  # type: ignore[union-attr]

    _run(f"routine resume {rid}", _session(ledger))
    assert ledger.routines.get(rid).status is RoutineStatus.ACTIVE  # type: ignore[union-attr]


def test_show_unknown_routine_is_reported(ledger: SqliteLedger) -> None:
    _, out = _run("routine show nope", _session(ledger))
    assert "nope" in out.lower() or "no " in out.lower()
