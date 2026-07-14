"""Durable management authority, Team, and delegation contract records (M8)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from chorus.ledger._models._enums import (
    DelegationContractStatus,
    TeamMembershipRole,
    TeamStatus,
)


@dataclass(frozen=True)
class ManagementProfile:
    """A bounded, human-granted management policy for one specialist."""

    employee_id: str
    granted_by_user_id: str
    active: bool = False
    can_lead: bool = False
    can_subdelegate: bool = False
    max_delegation_depth: int = 0
    max_team_size: int = 1
    allowed_professions: tuple[str, ...] = ()
    spend_limit_cents: int | None = None
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("management profile version must be at least 1")
        if self.max_delegation_depth < 0:
            raise ValueError("max_delegation_depth cannot be negative")
        if self.max_team_size < 1:
            raise ValueError("max_team_size must be at least 1")
        if self.spend_limit_cents is not None and self.spend_limit_cents < 0:
            raise ValueError("spend_limit_cents cannot be negative")


@dataclass(frozen=True)
class Team:
    """A durable group coordinating one delegated objective."""

    id: str
    name: str
    lead_employee_id: str
    created_by: str
    goal_id: str | None = None
    parent_team_id: str | None = None
    status: TeamStatus = TeamStatus.FORMING
    policy_version: int = 1
    created_at: datetime | None = None
    activated_at: datetime | None = None
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.policy_version < 1:
            raise ValueError("team policy_version must be at least 1")


@dataclass(frozen=True)
class TeamMember:
    """A Team responsibility grant; never a reporting edge."""

    team_id: str
    employee_id: str
    source_manager_id: str
    membership_role: TeamMembershipRole = TeamMembershipRole.MEMBER
    can_subdelegate: bool = False
    joined_at: datetime | None = None
    left_at: datetime | None = None


@dataclass(frozen=True)
class DelegationContract:
    """Pinned authority and completion semantics for one delegation-mode task."""

    task_id: str
    team_id: str
    lead_employee_id: str
    management_profile_version: int
    objective_rubric: str
    parent_contract_task_id: str | None = None
    can_subdelegate: bool = False
    max_depth: int = 0
    max_team_size: int = 1
    spend_limit_cents: int | None = None
    status: DelegationContractStatus = DelegationContractStatus.FORMING
    accepted_run_id: str | None = None
    accepted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.management_profile_version < 1:
            raise ValueError("management_profile_version must be at least 1")
        if self.max_depth < 0:
            raise ValueError("max_depth cannot be negative")
        if self.max_team_size < 1:
            raise ValueError("max_team_size must be at least 1")
        if self.spend_limit_cents is not None and self.spend_limit_cents < 0:
            raise ValueError("spend_limit_cents cannot be negative")