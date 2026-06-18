"""Fixtures for the chorus_tools tests (Path A: chorus capabilities as dream tools).

An in-memory migrated ledger — the tools mutate it directly; no network and no model in the loop.
"""

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
