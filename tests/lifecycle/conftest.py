"""Fixtures for the lifecycle / recovery tests (spec 02).

Same tiny harness as ``tests/ledger``: an in-memory migrated ledger, no dream and
no network — lifecycle rules are pure ledger logic.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from chorus.ledger import SqliteLedger
from chorus.workforce import Employee


@pytest.fixture
def ledger() -> Iterator[SqliteLedger]:
    """An open, migrated in-memory ledger facade (repos wired)."""
    lg = SqliteLedger.open(":memory:")
    try:
        yield lg
    finally:
        lg.close()


@pytest.fixture
def employee(ledger: SqliteLedger) -> Employee:
    """A persisted employee — checkout sets ``assignee_employee_id`` (an FK)."""
    return ledger.employees.create(Employee(id="emp_1", name="alice", role="engineer"))
