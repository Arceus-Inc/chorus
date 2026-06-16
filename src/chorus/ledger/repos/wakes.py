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

# The spec 03 §3 deterministic dispatch sort key, as a SQL ORDER BY fragment over aliases
# ``w`` (wake) and ``t`` (its target task, LEFT JOINed — NULL for a task-less wake):
#   resume first (in_progress) -> deps-ready first -> priority band -> FIFO -> wake id.
_DISPATCH_ORDER = (
    "CASE WHEN t.status = 'in_progress' THEN 0 ELSE 1 END, "
    "CASE WHEN t.id IS NOT NULL AND EXISTS ("
    "  SELECT 1 FROM task_dependency d JOIN task b ON b.id = d.depends_on_id "
    "  WHERE d.task_id = t.id AND b.status <> 'done'"
    ") THEN 1 ELSE 0 END, "
    "CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
    "WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, "
    "w.created_at, w.id"
)


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
        """Atomically take up to ``limit`` queued wakes in the kernel's dispatch order (spec 03 §3d).

        Order is the deterministic sort key, not arrival: an ``in_progress`` task (a resume) outranks
        a fresh ``todo``; a deps-ready task outranks a gated one; then the priority band; then FIFO
        (``created_at``); then the wake id. The claim is a single ``UPDATE … WHERE id IN (SELECT …
        ORDER BY … LIMIT) AND status='queued'`` so two concurrent claimers can't take the same wake;
        a follow-up read re-applies the order (``RETURNING`` order is unspecified).
        """
        if limit <= 0:
            return []
        now = utcnow_iso()
        claimed = self._conn.execute(
            "UPDATE wake SET status = 'claimed', claimed_at = ? WHERE id IN ("
            "  SELECT w.id FROM wake w "
            "  LEFT JOIN task t ON t.id = json_extract(w.payload, '$.task_id') "
            f"  WHERE w.status = 'queued' ORDER BY {_DISPATCH_ORDER} LIMIT ?"
            ") AND status = 'queued' RETURNING id",
            (now, limit),
        ).fetchall()
        self._conn.commit()
        if not claimed:
            return []
        ids = [row["id"] for row in claimed]
        placeholders = ", ".join("?" for _ in ids)
        ordered = self._conn.execute(
            f"SELECT w.* FROM wake w "
            f"LEFT JOIN task t ON t.id = json_extract(w.payload, '$.task_id') "
            f"WHERE w.id IN ({placeholders}) ORDER BY {_DISPATCH_ORDER}",
            ids,
        ).fetchall()
        return [_row_to_wake(row) for row in ordered]

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

    def release(self, wake_id: str) -> None:
        """Return a *claimed* wake to ``queued`` so a later tick re-claims it (spec 03 §5).

        The tick over-claims (up to the free-slot budget) then serializes per employee; a wake it
        can't dispatch this pulse (employee already has a live beat) is released, not stranded — its
        ``created_at`` is preserved so it keeps its FIFO position (anti-starvation).
        """
        self._conn.execute(
            "UPDATE wake SET status = 'queued', claimed_at = NULL "
            "WHERE id = ? AND status = 'claimed'",
            (wake_id,),
        )
        self._conn.commit()

    def drop_queued(self, *, employee_id: str | None = None) -> int:
        """Delete pending (``queued``) wakes, optionally scoped to one employee (spec 04 §3 kill).

        Returns how many were dropped. A hard budget breach cancels pending wakes so no new beat
        starts for the paused scope; ``employee_id=None`` clears the whole queue (company scope).
        Claimed/done wakes are left untouched.
        """
        if employee_id is None:
            cursor = self._conn.execute("DELETE FROM wake WHERE status = 'queued'")
        else:
            cursor = self._conn.execute(
                "DELETE FROM wake WHERE status = 'queued' AND employee_id = ?", (employee_id,)
            )
        self._conn.commit()
        return cursor.rowcount

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
