"""Typed workforce-plan drafts and durable governed revisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class WorkforcePlanStatus(StrEnum):
    """Lifecycle of one immutable workforce-plan revision."""

    PROPOSED = "proposed"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    APPLIED = "applied"


@dataclass(frozen=True)
class PlannedEmployee:
    """One permanent employee proposed by the CEO."""

    ref: str
    name: str
    profession: str
    reports_to_ref: str
    responsibilities: tuple[str, ...] = ()
    budget_cents: int | None = None

    def __post_init__(self) -> None:
        if not self.ref.strip() or not self.name.strip() or not self.profession.strip():
            raise ValueError("planned employee ref, name, and profession are required")
        if not self.reports_to_ref.strip():
            raise ValueError("planned employee reports_to_ref is required")
        if self.budget_cents is not None and self.budget_cents < 0:
            raise ValueError("planned employee budget cannot be negative")


@dataclass(frozen=True)
class ManagementGrantDraft:
    """One bounded management profile proposed for an existing or planned specialist."""

    employee_ref: str
    can_lead: bool
    can_subdelegate: bool
    max_delegation_depth: int
    max_team_size: int
    allowed_professions: tuple[str, ...] = ()
    spend_limit_cents: int | None = None

    def __post_init__(self) -> None:
        if not self.employee_ref.strip():
            raise ValueError("management grant employee_ref is required")
        if self.max_delegation_depth < 0:
            raise ValueError("management grant depth cannot be negative")
        if self.max_team_size < 1:
            raise ValueError("management grant team size must be at least one")
        if self.spend_limit_cents is not None and self.spend_limit_cents < 0:
            raise ValueError("management grant spend cannot be negative")


@dataclass(frozen=True)
class WorkforcePlanDraft:
    """The structured proposal body accepted from the CEO tool or a human revision."""

    rationale: str
    confidence: float
    source_goal_ids: tuple[str, ...]
    employees: tuple[PlannedEmployee, ...]
    management_grants: tuple[ManagementGrantDraft, ...]

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise ValueError("workforce plan rationale is required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("workforce plan confidence must be between zero and one")
        if not self.source_goal_ids:
            raise ValueError("workforce plan requires at least one source goal")
        if not self.employees:
            raise ValueError("workforce plan requires at least one proposed employee")


@dataclass(frozen=True)
class WorkforcePlan:
    """One immutable, durable revision of a governed workforce plan."""

    id: str
    revision: int
    status: WorkforcePlanStatus
    proposed_by_employee_id: str
    draft: WorkforcePlanDraft
    revised_by_user_id: str | None = None
    decided_by_user_id: str | None = None
    staffing_request_id: str | None = None
    created_at: datetime | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("workforce plan revision must be at least one")


__all__ = [
    "ManagementGrantDraft",
    "PlannedEmployee",
    "WorkforcePlan",
    "WorkforcePlanDraft",
    "WorkforcePlanStatus",
]