"""Fixtures for the budget-enforcement tests (spec 04 §3) — an in-memory migrated ledger."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from chorus.ledger import SqliteLedger


@pytest.fixture
def ledger() -> Iterator[SqliteLedger]:
    lg = SqliteLedger.open(":memory:")
    try:
        yield lg
    finally:
        lg.close()
