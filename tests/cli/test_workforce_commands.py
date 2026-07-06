"""The workforce lifecycle verbs — org as data, driven from the console (spec 06 §3).

``hire`` goes through the live :class:`LedgerWorkforce` (slug ids + org invariants);
``terminate`` / ``pause`` / ``resume`` mutate the employee status the invokability gate reads;
``workforce`` lists the org. These are the spec-06 inputs the scheduler's Gate 0 consults.
"""

from __future__ import annotations

import io

import pytest

from chorus.ledger import SqliteLedger
from chorus.workforce import EmployeeStatus
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    signal = dispatch(
        line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY
    )
    return signal, buffer.getvalue()


# -- hire (through the workforce) -------------------------------------------------------------------


def test_hire_mints_a_slug_id_and_persists_the_row(
    session: CliSession, ledger: SqliteLedger
) -> None:
    _, out = _run("hire Alice engineer", session)
    assert "hired alice (engineer)" in out
    assert ledger.employees.get("alice") is not None


def test_hire_with_reports_to_records_the_edge(session: CliSession, ledger: SqliteLedger) -> None:
    _run("hire Boss manager", session)
    _run("hire Alice engineer boss", session)
    assert ledger.employees.get("alice").reports_to == "boss"  # type: ignore[union-attr]


def test_hire_rejects_unknown_reports_to(session: CliSession) -> None:
    _, out = _run("hire Alice engineer ghost", session)
    assert "does not exist" in out


def test_hire_rejects_a_duplicate_slug(session: CliSession) -> None:
    _run("hire Alice engineer", session)
    _, out = _run("hire Alice reviewer", session)  # same name → same slug
    assert "already exists" in out


def test_hire_wrong_arity_reports_usage(session: CliSession) -> None:
    _, out = _run("hire Alice", session)
    assert "usage: hire" in out


# -- terminate --------------------------------------------------------------------------------------


def test_terminate_marks_terminated_and_cancels_work(
    session: CliSession, ledger: SqliteLedger
) -> None:
    _run("hire Boss manager", session)
    _run("hire Alice engineer boss", session)
    _, out = _run("terminate alice", session)
    assert ledger.employees.get("alice").status is EmployeeStatus.TERMINATED  # type: ignore[union-attr]
    assert "terminated alice" in out


def test_terminate_root_is_rejected(session: CliSession, ledger: SqliteLedger) -> None:
    _run("hire Boss manager", session)  # reports_to None → the org root
    _, out = _run("terminate boss", session)
    assert "root" in out
    assert ledger.employees.get("boss").status is not EmployeeStatus.TERMINATED  # type: ignore[union-attr]


def test_terminate_unknown_errors(session: CliSession) -> None:
    _, out = _run("terminate ghost", session)
    assert "no employee" in out


# -- pause / resume ---------------------------------------------------------------------------------


def test_pause_then_resume_round_trips_status(session: CliSession, ledger: SqliteLedger) -> None:
    _run("hire Alice engineer", session)
    _run("pause alice", session)
    assert ledger.employees.get("alice").status is EmployeeStatus.PAUSED  # type: ignore[union-attr]
    _run("resume alice", session)
    assert ledger.employees.get("alice").status is EmployeeStatus.IDLE  # type: ignore[union-attr]


def test_resume_does_not_revive_a_terminated_employee(
    session: CliSession, ledger: SqliteLedger
) -> None:
    _run("hire Boss manager", session)
    _run("hire Alice engineer boss", session)
    _run("terminate alice", session)
    _, out = _run("resume alice", session)
    assert "irreversible" in out
    assert ledger.employees.get("alice").status is EmployeeStatus.TERMINATED  # type: ignore[union-attr]


def test_pause_unknown_errors(session: CliSession) -> None:
    _, out = _run("pause ghost", session)
    assert "no such employee" in out


# -- workforce (list) -------------------------------------------------------------------------------


def test_workforce_lists_the_org(session: CliSession) -> None:
    _run("hire Boss manager", session)
    _run("hire Alice engineer boss", session)
    _, out = _run("workforce", session)
    assert "boss" in out
    assert "alice" in out
