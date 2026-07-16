"""Durable staffing gaps raised from active delegation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class StaffingRequestStatus(StrEnum):
    """Lifecycle of one staffing gap."""

    OPEN = "open"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class StaffingNeed:
    """One missing direct-report profession and headcount."""

    profession: str
    count: int = 1

    def __post_init__(self) -> None:
        if not self.profession.strip():
            raise ValueError("staffing need profession is required")
        if self.count < 1:
            raise ValueError("staffing need count must be at least one")


@dataclass(frozen=True)
class StaffingRequest:
    """A lead's durable request to fill a gap inside pinned authority."""

    id: str
    task_id: str
    goal_id: str
    team_id: str
    requested_by_employee_id: str
    rationale: str
    needs: tuple[StaffingNeed, ...]
    status: StaffingRequestStatus = StaffingRequestStatus.OPEN
    workforce_plan_id: str | None = None
    created_at: datetime | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise ValueError("staffing request rationale is required")
        if not self.needs:
            raise ValueError("staffing request requires at least one need")


__all__ = ["StaffingNeed", "StaffingRequest", "StaffingRequestStatus"]