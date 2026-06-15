"""WakeRepo — the coalescing push inbox (spec 01 Cluster C ``wake``, spec 03 §2).

``enqueue`` is an upsert against the partial-unique ``wake_queued_key_uq`` index: a duplicate while a
wake is still ``queued`` bumps ``coalesced_count`` (and refreshes the payload) instead of inserting,
so the employee runs once. ``claim`` atomically takes the oldest queued wakes and marks them
``claimed``. Coalescing applies *only* to queued wakes — a trigger arriving after a wake is claimed
enqueues fresh work.
"""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import Wake, WakeReason, WakeStatus
from chorus.ledger.repos._base import dumps, from_iso, loads, utcnow_iso


class WakeRepo:
    """Enqueue (coalescing), claim, and finish ``wake`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def enqueue(self, wake: Wake) -> Wake:
        """Enqueue a wake; coalesce onto an existing *queued* wake with the same key."""
        now = utcnow_iso()
        key = wake.coalesce_key or _default_key(wake)
        self._conn.execute(
            "INSERT INTO wake (id, employee_id, reason, payload, status, coalesce_key, "
            "coalesced_count, idempotency_key, run_id, created_at, claimed_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, NULL, NULL) "
            "ON CONFLICT (coalesce_key) WHERE status = 'queued' "
            "DO UPDATE SET coalesced_count = coalesced_count + 1, payload = excluded.payload",
            (
                wake.id,
                wake.employee_id,
                wake.reason.value,
                dumps(dict(wake.payload)),
                WakeStatus.QUEUED.value,
                key,
                wake.run_id,
                now,
            ),
        )
        self._conn.commit()
        # Return the persisted queued row for this key (the existing one on a coalesce). Under a
        # concurrent claimer the queued row may have moved to 'claimed' — fall back to the latest.
        row = self._conn.execute(
            "SELECT * FROM wake WHERE coalesce_key = ? AND status = ?",
            (key, WakeStatus.QUEUED.value),
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                "SELECT * FROM wake WHERE coalesce_key = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (key,),
            ).fetchone()
        if row is None:  # pragma: no cover - the row we just upserted must exist
            raise KeyError(key)
        return _row_to_wake(row)

    def claim(self, *, limit: int) -> list[Wake]:
        """Atomically take up to ``limit`` oldest queued wakes, marking them ``claimed`` (FIFO).

        The claim is a single ``UPDATE … WHERE id IN (SELECT … LIMIT) AND status='queued'`` so two
        concurrent claimers can't both take the same wake (no select-then-update race).
        """
        if limit <= 0:
            return []
        now = utcnow_iso()
        claimed = self._conn.execute(
            "UPDATE wake SET status = 'claimed', claimed_at = ? WHERE id IN "
            "(SELECT id FROM wake WHERE status = 'queued' ORDER BY created_at, id LIMIT ?) "
            "AND status = 'queued' RETURNING *",
            (now, limit),
        ).fetchall()
        self._conn.commit()
        # RETURNING order is unspecified; re-sort to FIFO (created_at ISO sorts chronologically).
        claimed.sort(key=lambda row: (row["created_at"], row["id"]))
        return [_row_to_wake(row) for row in claimed]

    def assign_run(self, wake_id: str, run_id: str) -> None:
        self._conn.execute("UPDATE wake SET run_id = ? WHERE id = ?", (run_id, wake_id))
        self._conn.commit()

    def mark_done(self, wake_id: str) -> None:
        """Finish a *claimed* wake; queued wakes are left untouched (lifecycle guard)."""
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE wake SET status = 'done', finished_at = ? WHERE id = ? AND status = 'claimed'",
            (now, wake_id),
        )
        self._conn.commit()

    def get(self, wake_id: str) -> Wake | None:
        row = self._conn.execute("SELECT * FROM wake WHERE id = ?", (wake_id,)).fetchone()
        return _row_to_wake(row) if row is not None else None

    def active_for_employee(self, employee_id: str) -> list[Wake]:
        """Live wakes (``queued`` or ``claimed``) for an employee — a liveness path (spec 02 §3).

        A claimed wake means a beat is about to run / is running; both keep the target task healthy.
        """
        rows = self._conn.execute(
            "SELECT * FROM wake WHERE employee_id = ? AND status IN ('queued', 'claimed') "
            "ORDER BY created_at, id",
            (employee_id,),
        ).fetchall()
        return [_row_to_wake(row) for row in rows]

    def by_coalesce_key(self, coalesce_key: str) -> list[Wake]:
        """Every wake ever filed under ``coalesce_key``, oldest first (spec 02 §5 disposition).

        Spans the queued/claimed/done boundary — the disposition reconciler reads it to tell a
        *delivered-then-consumed* finish-handoff from a still-pending one.
        """
        rows = self._conn.execute(
            "SELECT * FROM wake WHERE coalesce_key = ? ORDER BY created_at, id",
            (coalesce_key,),
        ).fetchall()
        return [_row_to_wake(row) for row in rows]

    def queued(self, *, employee_id: str | None = None) -> list[Wake]:
        """Queued wakes (oldest first), optionally scoped to one employee."""
        if employee_id is None:
            rows = self._conn.execute(
                "SELECT * FROM wake WHERE status = 'queued' ORDER BY created_at, id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM wake WHERE status = 'queued' AND employee_id = ? "
                "ORDER BY created_at, id",
                (employee_id,),
            ).fetchall()
        return [_row_to_wake(row) for row in rows]


def _default_key(wake: Wake) -> str:
    task = wake.payload.get("task_id", "")
    return f"{wake.employee_id}:{wake.reason.value}:{task}"


def _row_to_wake(row: sqlite3.Row) -> Wake:
    return Wake(
        id=row["id"],
        employee_id=row["employee_id"],
        reason=WakeReason(row["reason"]),
        payload=loads(row["payload"]) or {},
        status=WakeStatus(row["status"]),
        coalesce_key=row["coalesce_key"],
        coalesced_count=row["coalesced_count"],
        run_id=row["run_id"],
        created_at=from_iso(row["created_at"]),
        claimed_at=from_iso(row["claimed_at"]),
        finished_at=from_iso(row["finished_at"]),
    )
