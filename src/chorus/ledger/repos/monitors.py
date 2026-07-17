"""MonitorRepo — deferred one-shot self-wake (spec 01 Cluster B ``monitor``).

``arm`` records a pending monitor; the partial-unique ``monitor_armed_task_uq`` index allows only one
armed monitor per task. ``due`` is the scheduler's ripe-pending scan. ``fire`` is one-shot: it bumps
the bounded attempt counter and moves the monitor to ``fired`` (room to re-arm) or ``exhausted`` (no
attempts left). ``rearm`` returns a fired monitor to pending — rejected once exhausted. ``clear``
closes it when the task goes terminal or human-owned.
"""

from __future__ import annotations

from datetime import datetime

from chorus.ledger._models import Monitor, MonitorRecoveryPolicy, MonitorStatus
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    to_iso,
    utcnow_iso,
)


class MonitorRepo:
    """Arm, scan, fire, re-arm, and clear ``monitor`` rows."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def arm(self, monitor: Monitor) -> Monitor:
        """Record a pending monitor; only one armed monitor per task is allowed."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO monitor (id, task_id, employee_id, next_check_at, status, notes, "
            "external_ref, timeout_at, max_attempts, attempt_count, recovery_policy, created_at, "
            "fired_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                monitor.id,
                monitor.task_id,
                monitor.employee_id,
                to_iso(monitor.next_check_at),
                MonitorStatus.PENDING.value,
                monitor.notes,
                monitor.external_ref,
                to_iso(monitor.timeout_at),
                monitor.max_attempts,
                monitor.attempt_count,
                monitor.recovery_policy.value,
                now,
            ),
        )
        self._conn.commit()
        armed = require_persisted(self.get(monitor.id), monitor.id)
        return armed

    def get(self, monitor_id: str) -> Monitor | None:
        row = self._conn.execute("SELECT * FROM monitor WHERE id = ?", (monitor_id,)).fetchone()
        return _row_to_monitor(row) if row is not None else None

    def armed_for_task(self, task_id: str) -> Monitor | None:
        """The single armed (``pending``) monitor for a task, or ``None`` — a liveness path (§3)."""
        row = self._conn.execute(
            "SELECT * FROM monitor WHERE task_id = ? AND status = 'pending' "
            "ORDER BY next_check_at, id LIMIT 1",
            (task_id,),
        ).fetchone()
        return _row_to_monitor(row) if row is not None else None

    def due(self, *, now: datetime) -> list[Monitor]:
        """Pending monitors whose ``next_check_at`` has arrived, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM monitor WHERE status = 'pending' AND next_check_at IS NOT NULL "
            "AND next_check_at <= ? ORDER BY next_check_at, id",
            (to_iso(now),),
        ).fetchall()
        return [_row_to_monitor(row) for row in rows]

    def fire(self, monitor_id: str) -> Monitor:
        """One-shot fire: bump the attempt counter and move to fired (or exhausted)."""
        monitor = self.get(monitor_id)
        if monitor is None:
            raise KeyError(monitor_id)
        if monitor.status is not MonitorStatus.PENDING:
            raise ValueError(f"monitor {monitor_id} is {monitor.status.value}, not pending")
        attempts = monitor.attempt_count + 1
        exhausted = attempts >= monitor.max_attempts
        status = MonitorStatus.EXHAUSTED if exhausted else MonitorStatus.FIRED
        self._conn.execute(
            "UPDATE monitor SET status = ?, attempt_count = ?, fired_at = ? WHERE id = ?",
            (status.value, attempts, utcnow_iso(), monitor_id),
        )
        self._conn.commit()
        return self._reload(monitor_id)

    def rearm(self, monitor_id: str, *, next_check_at: datetime) -> Monitor:
        """Return a fired monitor to pending with a fresh check time (rejected if exhausted)."""
        monitor = self.get(monitor_id)
        if monitor is None:
            raise KeyError(monitor_id)
        if monitor.status is MonitorStatus.EXHAUSTED:
            raise ValueError("cannot re-arm an exhausted monitor")
        if monitor.status is not MonitorStatus.FIRED:
            raise ValueError(f"monitor {monitor_id} is {monitor.status.value}, not fired")
        self._conn.execute(
            "UPDATE monitor SET status = 'pending', next_check_at = ? WHERE id = ?",
            (to_iso(next_check_at), monitor_id),
        )
        self._conn.commit()
        return self._reload(monitor_id)

    def clear(self, monitor_id: str) -> None:
        """Close the monitor (task went terminal or human-owned), freeing the task."""
        self._conn.execute("UPDATE monitor SET status = 'cleared' WHERE id = ?", (monitor_id,))
        self._conn.commit()

    def _reload(self, monitor_id: str) -> Monitor:
        reloaded = require_persisted(self.get(monitor_id), monitor_id)
        return reloaded


def _row_to_monitor(row: LedgerRow) -> Monitor:
    return Monitor(
        id=row["id"],
        task_id=row["task_id"],
        employee_id=row["employee_id"],
        next_check_at=from_iso(row["next_check_at"]),
        status=MonitorStatus(row["status"]),
        notes=row["notes"],
        external_ref=row["external_ref"],
        timeout_at=from_iso(row["timeout_at"]),
        max_attempts=row["max_attempts"],
        attempt_count=row["attempt_count"],
        recovery_policy=MonitorRecoveryPolicy(row["recovery_policy"]),
        created_at=from_iso(row["created_at"]),
        fired_at=from_iso(row["fired_at"]),
    )
