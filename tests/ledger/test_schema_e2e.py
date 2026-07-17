"""End-to-end tests against the real schema (spec 01 Clusters A, C, D, F).

Exercises the load-bearing invariants directly in SQL on the bootstrapped Postgres schema: the
single-assignee XOR check, the atomic checkout CAS, and the exact-once partial-unique index.
"""

from __future__ import annotations

import pytest

from chorus.ledger import Ledger, LedgerConnection, LedgerIntegrityError
from chorus.testing import uid

pytestmark = pytest.mark.e2e

_NOW = "2026-06-15T00:00:00+00:00"


def _insert_employee(conn: LedgerConnection, eid: str) -> None:
    conn.execute(
        "INSERT INTO employee (id, name, role, created_at, updated_at) VALUES (?,?,?,?,?)",
        (eid, eid, "engineer", _NOW, _NOW),
    )
    conn.commit()


def _insert_task(conn: LedgerConnection, tid: str, **cols: str) -> None:
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


def test_all_m1_tables_exist(ledger: Ledger) -> None:
    rows = ledger._conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    ).fetchall()
    tables = {r["tablename"] for r in rows}
    assert {
        "employee",
        "goal",
        "task",
        "run",
        "dod",
        "artifact",
        "chorus_schema_migrations",
    } <= tables


def test_key_indexes_exist(ledger: Ledger) -> None:
    rows = ledger._conn.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
    ).fetchall()
    idx = {r["indexname"] for r in rows}
    assert {
        "dod_task_uq",
        "task_open_routine_uq",
        "task_active_stranded_recovery_uq",
    } <= idx


def test_single_assignee_xor_is_enforced(ledger: Ledger) -> None:
    _insert_employee(ledger._conn, uid("e1"))
    with pytest.raises(LedgerIntegrityError):
        _insert_task(
            ledger._conn, uid("t1"), assignee_employee_id=uid("e1"), assignee_user_id=uid("u1")
        )


def test_checkout_cas_grants_single_owner(ledger: Ledger) -> None:
    _insert_employee(ledger._conn, uid("e1"))
    _insert_task(ledger._conn, uid("t1"), status="todo")

    won = ledger._conn.execute(
        "UPDATE task SET checkout_run_id=?, status='in_progress', assignee_employee_id=? "
        "WHERE id=? AND checkout_run_id IS NULL",
        (uid("run1"), uid("e1"), uid("t1")),
    )
    ledger._conn.commit()
    assert won.rowcount == 1

    # A second claimant finds the lock taken → 0 rows (a 409, never a clobber).
    lost = ledger._conn.execute(
        "UPDATE task SET checkout_run_id=? WHERE id=? AND checkout_run_id IS NULL",
        (uid("run2"), uid("t1")),
    )
    ledger._conn.commit()
    assert lost.rowcount == 0


def test_exact_once_self_spawned_task(ledger: Ledger) -> None:
    _insert_task(
        ledger._conn,
        uid("r1"),
        origin_kind="stranded_recovery",
        origin_id=uid("src1"),
        status="todo",
    )
    with pytest.raises(LedgerIntegrityError):
        _insert_task(
            ledger._conn,
            uid("r2"),
            origin_kind="stranded_recovery",
            origin_id=uid("src1"),
            status="todo",
        )


def test_dod_is_one_per_task(ledger: Ledger) -> None:
    _insert_task(ledger._conn, uid("t1"), status="todo")
    ledger._conn.execute(
        "INSERT INTO dod (id, task_id, kind, created_at, updated_at) VALUES (?,?,?,?,?)",
        (uid("d1"), uid("t1"), "command", _NOW, _NOW),
    )
    ledger._conn.commit()
    with pytest.raises(LedgerIntegrityError):
        ledger._conn.execute(
            "INSERT INTO dod (id, task_id, kind, created_at, updated_at) VALUES (?,?,?,?,?)",
            (uid("d2"), uid("t1"), "agent_review", _NOW, _NOW),
        )
        ledger._conn.commit()


def test_schema_version_reports_the_baseline(ledger: Ledger) -> None:
    from chorus.ledger import baseline

    assert ledger.schema_version() == baseline()[0]
