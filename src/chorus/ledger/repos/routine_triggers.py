"""RoutineTriggerRepo — routine schedules (spec 01 Cluster C ``routine_trigger``).

``due`` is the scheduler's ripe scan. ``claim_fire`` is the double-fire guard: an optimistic
``UPDATE … WHERE next_run_at=<old>`` that advances the edge — only the tick still holding the current
edge wins, so two ticks can't fire the same trigger.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from chorus.ledger._models import RoutineTrigger, TriggerKind
from chorus.ledger.repos._base import from_iso, require_persisted, to_iso, utcnow_iso


class RoutineTriggerRepo:
    """Create, scan, and atomically fire ``routine_trigger`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, trigger: RoutineTrigger) -> RoutineTrigger:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO routine_trigger (id, routine_id, kind, cron_expression, timezone, "
            "next_run_at, last_fired_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trigger.id,
                trigger.routine_id,
                trigger.kind.value,
                trigger.cron_expression,
                trigger.timezone,
                to_iso(trigger.next_run_at),
                to_iso(trigger.last_fired_at),
                now,
            ),
        )
        self._conn.commit()
        created = require_persisted(self.get(trigger.id), trigger.id)
        return created

    def get(self, trigger_id: str) -> RoutineTrigger | None:
        row = self._conn.execute(
            "SELECT * FROM routine_trigger WHERE id = ?", (trigger_id,)
        ).fetchone()
        return _row_to_trigger(row) if row is not None else None

    def by_routine(self, routine_id: str) -> list[RoutineTrigger]:
        """A routine's triggers, oldest first (the read-model surface, spec 08 / 13 §7)."""
        rows = self._conn.execute(
            "SELECT * FROM routine_trigger WHERE routine_id = ? ORDER BY created_at, id",
            (routine_id,),
        ).fetchall()
        return [_row_to_trigger(row) for row in rows]

    def due(self, *, now: datetime) -> list[RoutineTrigger]:
        """Triggers whose ``next_run_at`` has arrived, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM routine_trigger WHERE next_run_at IS NOT NULL AND next_run_at <= ? "
            "ORDER BY next_run_at, id",
            (to_iso(now),),
        ).fetchall()
        return [_row_to_trigger(row) for row in rows]

    def claim_fire(
        self,
        trigger_id: str,
        *,
        expected_next_run_at: datetime,
        new_next_run_at: datetime,
    ) -> bool:
        """Advance the edge iff it still equals ``expected_next_run_at`` (the double-fire guard).

        Returns ``True`` if this caller won the fire, ``False`` if another tick already advanced it.
        """
        cur = self._conn.execute(
            "UPDATE routine_trigger SET next_run_at = ?, last_fired_at = ? "
            "WHERE id = ? AND next_run_at = ?",
            (to_iso(new_next_run_at), utcnow_iso(), trigger_id, to_iso(expected_next_run_at)),
        )
        self._conn.commit()
        return cur.rowcount == 1


def _row_to_trigger(row: sqlite3.Row) -> RoutineTrigger:
    return RoutineTrigger(
        id=row["id"],
        routine_id=row["routine_id"],
        kind=TriggerKind(row["kind"]),
        cron_expression=row["cron_expression"],
        timezone=row["timezone"],
        next_run_at=from_iso(row["next_run_at"]),
        last_fired_at=from_iso(row["last_fired_at"]),
        created_at=from_iso(row["created_at"]),
    )
