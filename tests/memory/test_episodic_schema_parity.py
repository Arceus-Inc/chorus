"""Schema ↔ migration parity for the episodic store (mirrors tests/ledger/test_schema_parity.py).

The declarative ``schema/`` folder and the applied ``migrations/`` ``.sql`` files are two views of
the same schema. Applying all migrations must produce *exactly* the objects ``schema/`` declares.
"""

from __future__ import annotations

import sqlite3
from importlib.resources import files

import pytest

from chorus.ledger._migrations import MigrationRunner
from chorus.memory.migrations import MIGRATIONS

pytestmark = pytest.mark.unit


def _normalized_objects(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name <> 'schema_migrations' "
        "ORDER BY type, name"
    ).fetchall()
    return [(str(r[0]), str(r[1]), " ".join(str(r[2]).split())) for r in rows]


def test_migrations_match_declared_schema() -> None:
    migrated = sqlite3.connect(":memory:")
    declared = sqlite3.connect(":memory:")
    try:
        MigrationRunner(MIGRATIONS).apply(migrated)
        for entry in sorted(files("chorus.memory.schema").iterdir(), key=lambda e: e.name):
            if entry.name.endswith(".sql"):
                declared.executescript(entry.read_text())
        migrated_objects = _normalized_objects(migrated)
        declared_objects = _normalized_objects(declared)
    finally:
        migrated.close()
        declared.close()
    assert migrated_objects == declared_objects
