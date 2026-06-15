"""Fixtures for the ledger / migration tests (spec 01).

The e2e harness is deliberately tiny: an in-memory SQLite connection, the real
migration set applied to it, and helpers to insert valid rows. No dream, no
network — the data layer is pure SQLite (spec 12).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from chorus.ledger import SqliteLedger
from chorus.ledger._migrations import MigrationRunner
from chorus.ledger.migrations import MIGRATIONS


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A fresh in-memory SQLite connection with FK enforcement on."""
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def runner() -> MigrationRunner:
    """A runner loaded with the real shipped migration set."""
    return MigrationRunner(MIGRATIONS)


@pytest.fixture
def migrated(conn: sqlite3.Connection, runner: MigrationRunner) -> sqlite3.Connection:
    """A connection with the full M1 schema applied."""
    runner.apply(conn)
    return conn


@pytest.fixture
def ledger() -> Iterator[SqliteLedger]:
    """An open, migrated in-memory ledger facade (repos wired)."""
    lg = SqliteLedger.open(":memory:")
    try:
        yield lg
    finally:
        lg.close()
