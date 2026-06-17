"""Fixtures for the workforce tests (spec 06 §3)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from chorus.ledger import SqliteLedger


@pytest.fixture
def ledger() -> Iterator[SqliteLedger]:
    """An open, migrated in-memory ledger facade (repos wired)."""
    lg = SqliteLedger.open(":memory:")
    try:
        yield lg
    finally:
        lg.close()
