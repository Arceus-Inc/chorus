"""ActivityRepo — the append-only audit stream (spec 01 Cluster G ``activity``, spec 08 §5).

Append-only: rows are written once and never updated. ``append`` records one auditable transition;
the single-actor XOR is enforced in the DB (both null = the kernel acted). ``by_subject`` returns one
row's history oldest-first; ``recent`` returns the global tail newest-first.
"""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import Activity, ActivityVerb
from chorus.ledger.repos._base import dumps, from_iso, loads, utcnow_iso


class ActivityRepo:
    """Append + read ``activity`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, activity: Activity) -> Activity:
        """Record one auditable transition; the single-actor XOR is enforced in the DB."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO activity (id, actor_employee_id, actor_user_id, verb, subject_kind, "
            "subject_id, trace_id, payload, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                activity.id,
                activity.actor_employee_id,
                activity.actor_user_id,
                activity.verb.value,
                activity.subject_kind,
                activity.subject_id,
                activity.trace_id,
                dumps(dict(activity.payload)),
                now,
            ),
        )
        self._conn.commit()
        recorded = self.get(activity.id)
        assert recorded is not None  # just inserted in this transaction
        return recorded

    def get(self, activity_id: str) -> Activity | None:
        row = self._conn.execute(
            "SELECT * FROM activity WHERE id = ?", (activity_id,)
        ).fetchone()
        return _row_to_activity(row) if row is not None else None

    def by_subject(self, subject_kind: str, subject_id: str) -> list[Activity]:
        """One row's audit history, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM activity WHERE subject_kind = ? AND subject_id = ? "
            "ORDER BY occurred_at, id",
            (subject_kind, subject_id),
        ).fetchall()
        return [_row_to_activity(row) for row in rows]

    def recent(self, *, limit: int) -> list[Activity]:
        """The global audit tail, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM activity ORDER BY occurred_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_activity(row) for row in rows]


def _row_to_activity(row: sqlite3.Row) -> Activity:
    return Activity(
        id=row["id"],
        verb=ActivityVerb(row["verb"]),
        subject_kind=row["subject_kind"],
        subject_id=row["subject_id"],
        actor_employee_id=row["actor_employee_id"],
        actor_user_id=row["actor_user_id"],
        trace_id=row["trace_id"],
        payload=loads(row["payload"]) or {},
        occurred_at=from_iso(row["occurred_at"]),
    )
