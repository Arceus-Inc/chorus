"""Unit tests for the applied-migration-set runner (spec 01 §schema-versioning).

These exercise the runner mechanics with *synthetic* migrations, independent of
the real M1 DDL, so the framework is verified in isolation.
"""

from __future__ import annotations

import sqlite3

import pytest

from chorus.ledger._migrations import (
    LedgerAheadError,
    Migration,
    MigrationDriftError,
    MigrationRunner,
)

pytestmark = pytest.mark.unit


def _mk(mid: str, *statements: str) -> Migration:
    return Migration(id=mid, statements=tuple(statements))


def test_apply_records_each_migration(conn: sqlite3.Connection) -> None:
    runner = MigrationRunner([_mk("0001_a", "CREATE TABLE a (x TEXT)")])
    applied = runner.apply(conn)
    assert applied == ["0001_a"]
    rows = conn.execute("SELECT id FROM schema_migrations ORDER BY id").fetchall()
    assert [r[0] for r in rows] == ["0001_a"]


def test_apply_is_idempotent(conn: sqlite3.Connection) -> None:
    runner = MigrationRunner([_mk("0001_a", "CREATE TABLE a (x TEXT)")])
    runner.apply(conn)
    assert runner.apply(conn) == []  # second run is a no-op
    count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == 1


def test_applies_in_id_order(conn: sqlite3.Connection) -> None:
    runner = MigrationRunner(
        [_mk("0002_b", "CREATE TABLE b (x TEXT)"), _mk("0001_a", "CREATE TABLE a (x TEXT)")]
    )
    assert runner.apply(conn) == ["0001_a", "0002_b"]


def test_incremental_apply_runs_only_new(conn: sqlite3.Connection) -> None:
    MigrationRunner([_mk("0001_a", "CREATE TABLE a (x TEXT)")]).apply(conn)
    newly = MigrationRunner(
        [_mk("0001_a", "CREATE TABLE a (x TEXT)"), _mk("0002_b", "CREATE TABLE b (x TEXT)")]
    ).apply(conn)
    assert newly == ["0002_b"]


def test_ledger_ahead_of_sdk_is_refused(conn: sqlite3.Connection) -> None:
    # DB has 0002_b applied; an older SDK that ships only 0001_a must refuse.
    MigrationRunner(
        [_mk("0001_a", "CREATE TABLE a (x TEXT)"), _mk("0002_b", "CREATE TABLE b (x TEXT)")]
    ).apply(conn)
    with pytest.raises(LedgerAheadError):
        MigrationRunner([_mk("0001_a", "CREATE TABLE a (x TEXT)")]).apply(conn)


def test_checksum_drift_is_refused(conn: sqlite3.Connection) -> None:
    # A migration edited after it was applied must be rejected, not silently re-run.
    MigrationRunner([_mk("0001_a", "CREATE TABLE a (x TEXT)")]).apply(conn)
    with pytest.raises(MigrationDriftError):
        MigrationRunner([_mk("0001_a", "CREATE TABLE a (y TEXT)")]).apply(conn)


def test_display_version_is_max_applied_id(conn: sqlite3.Connection) -> None:
    runner = MigrationRunner(
        [_mk("0001_a", "CREATE TABLE a (x TEXT)"), _mk("0002_b", "CREATE TABLE b (x TEXT)")]
    )
    assert runner.display_version(conn) is None
    runner.apply(conn)
    assert runner.display_version(conn) == "0002_b"


def test_pending_lists_unapplied(conn: sqlite3.Connection) -> None:
    runner = MigrationRunner(
        [_mk("0001_a", "CREATE TABLE a (x TEXT)"), _mk("0002_b", "CREATE TABLE b (x TEXT)")]
    )
    assert runner.pending(conn) == ["0001_a", "0002_b"]
    MigrationRunner([_mk("0001_a", "CREATE TABLE a (x TEXT)")]).apply(conn)
    assert runner.pending(conn) == ["0002_b"]


def test_failed_migration_rolls_back_atomically(conn: sqlite3.Connection) -> None:
    # Second statement errors (duplicate table) → no row recorded, first table gone.
    bad = _mk("0001_bad", "CREATE TABLE ok (x TEXT)", "CREATE TABLE ok (x TEXT)")
    with pytest.raises(sqlite3.OperationalError):
        MigrationRunner([bad]).apply(conn)
    recorded = conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE id = '0001_bad'"
    ).fetchone()[0]
    assert recorded == 0
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ok" not in tables


def test_checksum_is_stable_and_content_sensitive() -> None:
    a1 = _mk("0001_a", "CREATE TABLE a (x TEXT)")
    a2 = _mk("0001_a", "CREATE TABLE a (x TEXT)")
    b = _mk("0001_a", "CREATE TABLE a (y TEXT)")
    assert a1.checksum == a2.checksum
    assert a1.checksum != b.checksum


def test_reads_do_not_create_table_or_commit(conn: sqlite3.Connection) -> None:
    # Read paths must tolerate a missing table and never create/commit (no caller-tx side effects).
    runner = MigrationRunner([_mk("0001_a", "CREATE TABLE a (x TEXT)")])
    assert runner.applied(conn) == {}
    assert runner.display_version(conn) is None
    assert runner.pending(conn) == ["0001_a"]
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "schema_migrations" not in tables
