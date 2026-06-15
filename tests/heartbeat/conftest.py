"""Fixtures for the heartbeat / scheduler tests (spec 03).

Same tiny harness as the ledger suite: an in-memory ledger facade with the real
migrations applied, no dream, no network — the dispatch substrate is pure SQLite.
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
