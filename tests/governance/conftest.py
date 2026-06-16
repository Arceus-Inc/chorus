"""Fixtures for the governance resolver tests — an in-memory ledger, migrations applied."""

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
