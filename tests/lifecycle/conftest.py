"""Fixtures for the lifecycle / recovery tests (spec 02).

Same tiny harness as ``tests/ledger``: an in-memory migrated ledger, no dream and
no network — lifecycle rules are pure ledger logic.
"""

from __future__ import annotations

import pytest

from chorus.ledger import Ledger
from chorus.workforce import Employee


@pytest.fixture
def employee(ledger: Ledger) -> Employee:
    """A persisted employee — checkout sets ``assignee_employee_id`` (an FK)."""
    return ledger.employees.create(Employee(id="emp_1", name="alice", role="engineer"))
