"""Migration 0019 — routine becomes versioned (spec 13 §2, M4 S2).

The revision pin needs three schema changes: ``routine`` gains the head pointer + env + reconcile
key, a new ``routine_revision`` table holds the append-only history, and ``routine_run`` records the
revision each firing fired under. This pins the *migration* shape and, crucially, that an existing
routine is carried forward with a synthesized revision 1 (the data migration is not a fresh-DB no-op
by accident — it is correct when rows are present).
"""

from __future__ import annotations

import sqlite3

import pytest

from chorus.ledger._migrations import MigrationRunner
from chorus.ledger.migrations import MIGRATIONS

pytestmark = pytest.mark.unit

_S2 = "0019_routine_revisions"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {str(r[0]) for r in rows}


def test_routine_gains_revision_pin_env_and_reconcile_key() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        MigrationRunner(MIGRATIONS).apply(conn)
        cols = _columns(conn, "routine")
        assert {"env", "routine_key", "latest_revision_id", "latest_revision_no"} <= cols
        assert "routine_employee_key_uq" in _index_names(conn)
    finally:
        conn.close()


def test_routine_revision_table_exists_with_history_columns() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        MigrationRunner(MIGRATIONS).apply(conn)
        cols = _columns(conn, "routine_revision")
        assert {
            "id", "routine_id", "revision_no", "intent_template", "target",
            "concurrency_policy", "catch_up_policy", "env", "change_summary",
            "restored_from_revision_id", "created_at",
        } <= cols
        assert "routine_revision_no_uq" in _index_names(conn)
    finally:
        conn.close()


def test_routine_run_pins_the_revision_it_fired_under() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        MigrationRunner(MIGRATIONS).apply(conn)
        assert "routine_revision_id" in _columns(conn, "routine_run")
    finally:
        conn.close()


def test_existing_routine_is_carried_forward_with_a_synthesized_revision_1() -> None:
    """Apply everything before S2, seed an old-shape routine, then apply 0019: it must synthesize a
    revision 1 from the routine's current definition and point ``latest_revision_id`` at it."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        before = MigrationRunner([m for m in MIGRATIONS if m.id < _S2])
        before.apply(conn)
        conn.execute(
            "INSERT INTO employee (id, name, role, status, created_at, updated_at) "
            "VALUES ('e1', 'Ada', 'pm', 'active', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO routine (id, employee_id, intent_template, target, concurrency_policy, "
            "catch_up_policy, status, created_at, updated_at) "
            "VALUES ('r1', 'e1', 'weekly plan', 'spawn_task', 'coalesce', 'skip_missed', 'active', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()

        MigrationRunner(MIGRATIONS).apply(conn)  # runs only 0019

        routine = conn.execute("SELECT * FROM routine WHERE id = 'r1'").fetchone()
        assert routine["latest_revision_no"] == 1
        head_id = routine["latest_revision_id"]
        assert head_id is not None

        rev = conn.execute(
            "SELECT * FROM routine_revision WHERE id = ?", (head_id,)
        ).fetchone()
        assert rev is not None
        assert rev["routine_id"] == "r1"
        assert rev["revision_no"] == 1
        assert rev["intent_template"] == "weekly plan"  # snapshot of the live definition
        assert rev["restored_from_revision_id"] is None
    finally:
        conn.close()
