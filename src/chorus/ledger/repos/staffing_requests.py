"""Persistence for durable staffing requests and normalized needs."""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import StaffingNeed, StaffingRequest, StaffingRequestStatus
from chorus.ledger.repos._base import from_iso, require_persisted, utcnow_iso


class StaffingRequestRepo:
    """Store, link, and resolve staffing requests."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, request: StaffingRequest) -> StaffingRequest:
        self._conn.execute(
            "INSERT INTO staffing_request (id, task_id, goal_id, team_id, "
            "requested_by_employee_id, rationale, status, workforce_plan_id, created_at, "
            "resolved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request.id,
                request.task_id,
                request.goal_id,
                request.team_id,
                request.requested_by_employee_id,
                request.rationale,
                request.status.value,
                request.workforce_plan_id,
                utcnow_iso(),
                request.resolved_at.isoformat() if request.resolved_at is not None else None,
            ),
        )
        for need in request.needs:
            self._conn.execute(
                "INSERT INTO staffing_request_need (request_id, profession, count) "
                "VALUES (?, ?, ?)",
                (request.id, need.profession, need.count),
            )
        self._conn.commit()
        return require_persisted(self.get(request.id), request.id)

    def get(self, request_id: str) -> StaffingRequest | None:
        row = self._conn.execute(
            "SELECT * FROM staffing_request WHERE id = ?", (request_id,)
        ).fetchone()
        return self._row_to_request(row) if row is not None else None

    def list(self, *, status: StaffingRequestStatus | None = None) -> list[StaffingRequest]:
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM staffing_request ORDER BY created_at, id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM staffing_request WHERE status = ? ORDER BY created_at, id",
                (status.value,),
            ).fetchall()
        return [self._row_to_request(row) for row in rows]

    def link_plan(self, request_id: str, plan_id: str) -> StaffingRequest:
        self._conn.execute(
            "UPDATE staffing_request SET workforce_plan_id = ? "
            "WHERE id = ? AND status = ?",
            (plan_id, request_id, StaffingRequestStatus.OPEN.value),
        )
        self._conn.commit()
        return require_persisted(self.get(request_id), request_id)

    def fulfil(self, request_id: str, plan_id: str) -> StaffingRequest:
        self._conn.execute(
            "UPDATE staffing_request SET status = ?, workforce_plan_id = ?, resolved_at = ? "
            "WHERE id = ? AND status = ?",
            (
                StaffingRequestStatus.FULFILLED.value,
                plan_id,
                utcnow_iso(),
                request_id,
                StaffingRequestStatus.OPEN.value,
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(request_id), request_id)

    def _row_to_request(self, row: sqlite3.Row) -> StaffingRequest:
        needs = self._conn.execute(
            "SELECT profession, count FROM staffing_request_need WHERE request_id = ? "
            "ORDER BY profession",
            (row["id"],),
        ).fetchall()
        return StaffingRequest(
            id=row["id"],
            task_id=row["task_id"],
            goal_id=row["goal_id"],
            team_id=row["team_id"],
            requested_by_employee_id=row["requested_by_employee_id"],
            rationale=row["rationale"],
            needs=tuple(StaffingNeed(item["profession"], item["count"]) for item in needs),
            status=StaffingRequestStatus(row["status"]),
            workforce_plan_id=row["workforce_plan_id"],
            created_at=from_iso(row["created_at"]),
            resolved_at=from_iso(row["resolved_at"]),
        )


__all__ = ["StaffingRequestRepo"]