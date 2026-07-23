"""LedgerWorkforce — the ledger-backed live Workforce (spec 06 §3).

The same structural invariants as :class:`GitWorkforce` (no ``reports_to`` cycle / self-edge, no
duplicate slug, ``terminate`` is irreversible, the org root cannot be terminated, ``list`` excludes
terminated) — but the org lives in the ledger ``employee`` table, the single runtime source of truth
that every FK (``task.assignee_employee_id``, ``run.employee_id``, ``wake.employee_id``, …) points
at. A hired employee is therefore a real, assignable ledger row, not a markdown file.
"""

from __future__ import annotations

import pytest

from chorus.errors import OrgInvariantViolation, UnknownEmployee
from chorus.ledger import Ledger
from chorus.workforce import EmployeeStatus, LedgerWorkforce

pytestmark = pytest.mark.integration


@pytest.fixture
def wf(ledger: Ledger) -> LedgerWorkforce:
    return LedgerWorkforce(ledger.employees)


def test_hire_then_get_roundtrips(wf: LedgerWorkforce) -> None:
    hired = wf.hire(name="Alice", role="engineer")
    assert hired.id == "alice"
    assert hired.name == "Alice"
    assert hired.role == "engineer"
    assert hired.reports_to is None
    assert hired.status is EmployeeStatus.IDLE
    assert wf.get("alice") == hired


def test_hired_employee_is_a_real_assignable_ledger_row(
    ledger: Ledger, wf: LedgerWorkforce
) -> None:
    # The point of the fix: hire writes the ledger employee table the FKs point at.
    wf.hire(name="Alice", role="engineer")
    assert ledger.employees.get("alice") is not None


def test_hire_with_reports_to_records_the_edge(wf: LedgerWorkforce) -> None:
    wf.hire(name="Boss", role="engineer")
    report = wf.hire(name="Alice", role="engineer", reports_to="boss")
    assert report.reports_to == "boss"


def test_memory_scope_defaults_to_project(wf: LedgerWorkforce) -> None:
    assert wf.hire(name="Alice", role="engineer").memory_scope == "project"


def test_get_unknown_raises(wf: LedgerWorkforce) -> None:
    with pytest.raises(UnknownEmployee):
        wf.get("nobody")


def test_hire_unknown_reports_to_raises(wf: LedgerWorkforce) -> None:
    with pytest.raises(UnknownEmployee):
        wf.hire(name="Alice", role="engineer", reports_to="ghost")


def test_hire_empty_slug_is_rejected(wf: LedgerWorkforce) -> None:
    with pytest.raises(OrgInvariantViolation):
        wf.hire(name="   ", role="engineer")


def test_hire_self_edge_is_rejected(wf: LedgerWorkforce) -> None:
    # "Boss" slugs to "boss"; reporting to its own slug is a self-cycle.
    with pytest.raises(OrgInvariantViolation):
        wf.hire(name="Boss", role="engineer", reports_to="boss")


def test_hire_duplicate_slug_is_rejected(wf: LedgerWorkforce) -> None:
    wf.hire(name="Alice", role="engineer")
    with pytest.raises(OrgInvariantViolation):
        wf.hire(name="alice", role="reviewer")


def test_list_excludes_terminated(wf: LedgerWorkforce) -> None:
    wf.hire(name="Boss", role="engineer")
    wf.hire(name="Alice", role="engineer", reports_to="boss")
    wf.terminate("alice")
    assert {e.id for e in wf.list()} == {"boss"}


def test_terminate_marks_terminated_irreversibly(wf: LedgerWorkforce) -> None:
    wf.hire(name="Boss", role="engineer")
    wf.hire(name="Alice", role="engineer", reports_to="boss")
    wf.terminate("alice")
    assert wf.get("alice").status is EmployeeStatus.TERMINATED


def test_terminate_is_idempotent(wf: LedgerWorkforce) -> None:
    wf.hire(name="Boss", role="engineer")
    wf.hire(name="Alice", role="engineer", reports_to="boss")
    wf.terminate("alice")
    wf.terminate("alice")  # no raise — irreversible, not an error to repeat
    assert wf.get("alice").status is EmployeeStatus.TERMINATED


def test_terminate_root_is_rejected(wf: LedgerWorkforce) -> None:
    wf.hire(name="Boss", role="engineer")  # reports_to is None -> the org root
    with pytest.raises(OrgInvariantViolation):
        wf.terminate("boss")


def test_terminate_unknown_raises(wf: LedgerWorkforce) -> None:
    with pytest.raises(UnknownEmployee):
        wf.terminate("nobody")
