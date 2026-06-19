"""CLI verbs to test §4 trust, §5 governed hire, and §1 dod-show from the console (by hand)."""

from __future__ import annotations

import io

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.trust import TrustPreset
from chorus.workforce import Employee, EmployeeStatus
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    dispatch(line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY)
    return LoopSignal.CONTINUE, buffer.getvalue()


def _engineer_task(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="ada", name="ada", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="review an external PR", status=TaskStatus.TODO))
    assign_task(ledger, "t1", "ada")


# -- §4 trust --------------------------------------------------------------------------------------


def test_trust_set_and_show_low_trust_clamps(session: CliSession, ledger: SqliteLedger) -> None:
    _engineer_task(ledger)
    _, out = _run("trust set t1 low_trust_review ref:github_token", session)
    assert "set low_trust_review on t1" in out
    assert ledger.tasks.get("t1").trust_preset == TrustPreset.LOW_TRUST_REVIEW  # type: ignore[union-attr]

    _, shown = _run("trust show t1", session)
    assert "sandbox=read-only" in shown and "permission_mode=plan" in shown


def test_trust_show_denies_low_trust_without_a_boundary(session: CliSession, ledger: SqliteLedger) -> None:
    _engineer_task(ledger)
    _run("trust set t1 low_trust_review", session)  # no secret refs → no boundary
    _, shown = _run("trust show t1", session)
    assert "DENIED" in shown


def test_trust_show_standard_keeps_role_posture(session: CliSession, ledger: SqliteLedger) -> None:
    _engineer_task(ledger)
    _, shown = _run("trust show t1", session)
    assert "preset=standard" in shown


# -- §5 governed hire ------------------------------------------------------------------------------


def test_request_hire_opens_a_gate_and_approval_activates(
    session: CliSession, ledger: SqliteLedger
) -> None:
    _, out = _run("request-hire Bob engineer", session)
    assert "pending" in out
    assert ledger.employees.get("bob").status is EmployeeStatus.PENDING  # type: ignore[union-attr]

    gate = ledger.approvals.pending()[0].id
    _run(f"approval approve {gate}", session)
    assert ledger.employees.get("bob").status is EmployeeStatus.ACTIVE  # type: ignore[union-attr]


# -- §1 dod show -----------------------------------------------------------------------------------


def test_dod_show_reports_kind_and_revision(session: CliSession, ledger: SqliteLedger) -> None:
    ledger.tasks.submit(Task(id="t1", intent="ship", status=TaskStatus.TODO))
    _run("dod set t1 command pytest", session)
    _, shown = _run("dod show t1", session)
    assert "command DoD (rev 1" in shown
