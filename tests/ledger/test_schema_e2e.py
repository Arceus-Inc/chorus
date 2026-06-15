"""End-to-end tests against the real M1 schema (spec 01 Clusters A, C, D, F).

Applies the shipped migrations to a fresh SQLite DB and exercises the
load-bearing invariants directly in SQL: the single-assignee XOR check, the
atomic checkout CAS, and the exact-once partial-unique index.
"""

from __future__ import annotations

import sqlite3

import pytest

pytestmark = pytest.mark.e2e

_NOW = "2026-06-15T00:00:00+00:00"


def _insert_employee(conn: sqlite3.Connection, eid: str) -> None:
    conn.execute(
        "INSERT INTO employee (id, name, role, created_at, updated_at) VALUES (?,?,?,?,?)",
        (eid, eid, "engineer", _NOW, _NOW),
    )
    conn.commit()


def _insert_task(conn: sqlite3.Connection, tid: str, **cols: str) -> None:
    base: dict[str, object] = {
        "id": tid,
        "intent": "do a thing",
        "status": "backlog",
        "priority": "medium",
        "origin_kind": "manual",
        "origin_fingerprint": "default",
        "depth": 0,
        "request_depth": 0,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(cols)
    keys = ", ".join(base)
    marks = ", ".join("?" for _ in base)
    conn.execute(f"INSERT INTO task ({keys}) VALUES ({marks})", tuple(base.values()))
    conn.commit()


def test_all_m1_tables_exist(migrated: sqlite3.Connection) -> None:
    tables = {r[0] for r in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"employee", "goal", "task", "run", "dod", "artifact", "schema_migrations"} <= tables


def test_key_indexes_exist(migrated: sqlite3.Connection) -> None:
    idx = {r[0] for r in migrated.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {
        "dod_task_uq",
        "task_open_routine_uq",
        "task_active_stranded_recovery_uq",
    } <= idx


def test_single_assignee_xor_is_enforced(migrated: sqlite3.Connection) -> None:
    _insert_employee(migrated, "e1")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_task(migrated, "t1", assignee_employee_id="e1", assignee_user_id="u1")


def test_checkout_cas_grants_single_owner(migrated: sqlite3.Connection) -> None:
    _insert_employee(migrated, "e1")
    _insert_task(migrated, "t1", status="todo")

    won = migrated.execute(
        "UPDATE task SET checkout_run_id=?, status='in_progress', assignee_employee_id=? "
        "WHERE id=? AND checkout_run_id IS NULL",
        ("run1", "e1", "t1"),
    )
    migrated.commit()
    assert won.rowcount == 1

    # A second claimant finds the lock taken → 0 rows (a 409, never a clobber).
    lost = migrated.execute(
        "UPDATE task SET checkout_run_id=? WHERE id=? AND checkout_run_id IS NULL",
        ("run2", "t1"),
    )
    migrated.commit()
    assert lost.rowcount == 0


def test_exact_once_self_spawned_task(migrated: sqlite3.Connection) -> None:
    _insert_task(migrated, "r1", origin_kind="stranded_recovery", origin_id="src1", status="todo")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_task(
            migrated, "r2", origin_kind="stranded_recovery", origin_id="src1", status="todo"
        )


def test_dod_is_one_per_task(migrated: sqlite3.Connection) -> None:
    _insert_task(migrated, "t1", status="todo")
    migrated.execute(
        "INSERT INTO dod (id, task_id, kind, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("d1", "t1", "command", _NOW, _NOW),
    )
    migrated.commit()
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(
            "INSERT INTO dod (id, task_id, kind, created_at, updated_at) VALUES (?,?,?,?,?)",
            ("d2", "t1", "agent_review", _NOW, _NOW),
        )
        migrated.commit()


def test_display_version_reports_latest_migration(
    migrated: sqlite3.Connection, runner: object
) -> None:
    from chorus.ledger._migrations import MigrationRunner

    assert isinstance(runner, MigrationRunner)
    assert runner.display_version(migrated) == "0001_m1_core"
