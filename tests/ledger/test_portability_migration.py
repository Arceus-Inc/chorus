"""Migration 0029 (portability) — the data backfill, tested against legacy-shape rows.

The parity test proves post-migration DDL; this proves the one-shot row rewrite: wake.task_id
backfilled from the JSON payload (NULL-safe), and plan employee/grant position backfilled in
insertion (rowid) order. Also guards the migration id convention itself: numeric prefixes must be
unique (two different 0027s once slipped through — the id is the full stem, so the runner's
duplicate-id check alone doesn't catch it).
"""

from __future__ import annotations

import sqlite3
from collections import Counter

import pytest

from chorus.ledger._migrations import MigrationRunner
from chorus.ledger.migrations import MIGRATIONS

pytestmark = pytest.mark.unit


def test_migration_numeric_prefixes_are_unique() -> None:
    prefixes = Counter(migration.id.split("_", 1)[0] for migration in MIGRATIONS)
    duplicated = {prefix: count for prefix, count in prefixes.items() if count > 1}
    assert duplicated == {}, f"duplicate migration numbers: {duplicated}"


def _apply_up_to(conn: sqlite3.Connection, stop_before: str) -> None:
    kept = [migration for migration in MIGRATIONS if migration.id < stop_before]
    MigrationRunner(kept).apply(conn)


def test_backfills_wake_task_id_and_plan_positions() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_up_to(conn, stop_before="0029_portability")

    # Legacy-shape rows: wake.task_id does not exist yet; position does not exist yet.
    conn.execute(
        "INSERT INTO employee (id, name, role, created_at, updated_at) "
        "VALUES ('e1', 'a', 'engineer', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO wake (id, employee_id, reason, payload, status, coalesce_key, created_at) "
        "VALUES ('w1', 'e1', 'deps_resolved', '{\"task_id\": \"t9\"}', 'queued', 'k1', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO wake (id, employee_id, reason, payload, status, coalesce_key, created_at) "
        "VALUES ('w2', 'e1', 'recovery', '{}', 'queued', 'k2', '2026-01-01')"  # no task_id key
    )
    conn.execute(
        "INSERT INTO workforce_plan (id, status, proposed_by_employee_id, rationale, confidence, "
        "source_goal_ids, revision, created_at) "
        "VALUES ('p1', 'proposed', 'e1', 'r', 0.9, '[]', 1, '2026-01-01')"
    )
    for ref in ("third", "first", "second"):  # insertion order != alphabetical, on purpose
        conn.execute(
            "INSERT INTO workforce_plan_employee (plan_id, plan_revision, employee_ref, name, "
            "profession, reports_to_ref) VALUES ('p1', 1, ?, ?, 'engineer', 'ceo')",
            (ref, ref),
        )
    conn.commit()

    MigrationRunner(MIGRATIONS).apply(conn)  # applies exactly the pending 0029

    wakes = {
        row["id"]: row["task_id"] for row in conn.execute("SELECT id, task_id FROM wake").fetchall()
    }
    assert wakes == {"w1": "t9", "w2": None}  # backfilled from payload; NULL-safe on absent key

    order = [
        row["employee_ref"]
        for row in conn.execute(
            "SELECT employee_ref FROM workforce_plan_employee "
            "WHERE plan_id = 'p1' AND plan_revision = 1 ORDER BY position"
        ).fetchall()
    ]
    assert order == ["third", "first", "second"]  # insertion order preserved as explicit data
