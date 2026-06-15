"""Schema ↔ migration parity (spec 01 §schema-versioning).

The declarative ``schema/`` folder and the applied ``migrations/`` ``.sql`` files are two views of
the same schema. Without an ORM to generate one from the other, this test is the guard: applying all
migrations must produce *exactly* the objects ``schema/`` declares (same tables + indexes, by
normalised DDL). If they drift, this fails — edit both, or it won't merge.
"""

from __future__ import annotations

import sqlite3
from importlib.resources import files

import pytest

from chorus.ledger._migrations import MigrationRunner
from chorus.ledger.migrations import MIGRATIONS

pytestmark = pytest.mark.unit


def _normalized_objects(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """(type, name, whitespace-normalised SQL) for every user table/index, sorted.

    Excludes ``schema_migrations`` (runner-owned, not part of the declared schema) and
    SQLite's auto indexes. Whitespace is collapsed so formatting differences don't matter.
    """
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name <> 'schema_migrations' "
        "ORDER BY type, name"
    ).fetchall()
    return [(str(r[0]), str(r[1]), " ".join(str(r[2]).split())) for r in rows]


def test_migrations_match_declared_schema() -> None:
    migrated = sqlite3.connect(":memory:")
    MigrationRunner(MIGRATIONS).apply(migrated)

    declared = sqlite3.connect(":memory:")
    for entry in sorted(files("chorus.ledger.schema").iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".sql"):
            declared.executescript(entry.read_text())

    assert _normalized_objects(migrated) == _normalized_objects(declared)
