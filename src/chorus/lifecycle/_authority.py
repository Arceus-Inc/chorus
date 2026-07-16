"""Least-privilege intersection for M8 management authority layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from chorus.ledger._models import (
    DelegationContract,
    ExecutionMode,
    ManagementProfile,
    Task,
    TeamMembershipRole,
    TeamStatus,
)
from chorus.workforce import Employee, EmployeeStatus

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger


@dataclass(frozen=True)
class AuthorityLimits:
    """One authority layer; empty professions and ``None`` spend mean uncapped."""

    max_depth: int
    max_team_size: int
    spend_limit_cents: int | None = None
    allowed_professions: frozenset[str] = frozenset()
    can_subdelegate: bool = True

    def __post_init__(self) -> None:
        if self.max_depth < 0:
            raise ValueError("max_depth cannot be negative")
        if self.max_team_size < 1:
            raise ValueError("max_team_size must be at least 1")
        if self.spend_limit_cents is not None and self.spend_limit_cents < 0:
            raise ValueError("spend_limit_cents cannot be negative")


EffectiveAuthority = AuthorityLimits


@dataclass(frozen=True)
class AuthorizationResult:
    """A service-layer authority decision with the effective limits on success."""

    authorized: bool
    reason: str = ""
    effective: EffectiveAuthority | None = None


class AuthorityIntersection:
    """Compute effective authority without allowing any input layer to widen another."""

    def __init__(
        self,
        ledger: SqliteLedger | None = None,
        *,
        global_limits: AuthorityLimits | None = None,
    ) -> None:
        self._ledger = ledger
        self._global_limits = global_limits or AuthorityLimits(
            max_depth=5,
            max_team_size=2**31 - 1,
        )

    @staticmethod
    def intersect(*layers: AuthorityLimits) -> EffectiveAuthority:
        if not layers:
            raise ValueError("at least one authority layer is required")
        bounded_spend = [
            layer.spend_limit_cents
            for layer in layers
            if layer.spend_limit_cents is not None
        ]
        bounded_professions = [
            layer.allowed_professions for layer in layers if layer.allowed_professions
        ]
        allowed_professions = (
            frozenset.intersection(*bounded_professions)
            if bounded_professions
            else frozenset()
        )
        return AuthorityLimits(
            max_depth=min(layer.max_depth for layer in layers),
            max_team_size=min(layer.max_team_size for layer in layers),
            spend_limit_cents=min(bounded_spend) if bounded_spend else None,
            allowed_professions=allowed_professions,
            can_subdelegate=all(layer.can_subdelegate for layer in layers),
        )

    def check(
        self,
        employee: Employee,
        task: Task,
        target: Employee | None = None,
        *,
        requested_mode: ExecutionMode = ExecutionMode.DELIVERY,
    ) -> AuthorizationResult:
        """Authorize one mutation against every persisted authority layer."""
        if task.execution_mode is ExecutionMode.DELIVERY:
            return AuthorizationResult(True, effective=self._global_limits)
        if self._ledger is None:
            raise RuntimeError("ledger-aware authority checks require a ledger")
        if task.assignee_employee_id != employee.id:
            return _denied("actor is not the delegation contract lead")
        contract = self._ledger.delegation_contracts.active_for_task(task.id)
        if contract is None or contract.lead_employee_id != employee.id:
            return _denied("actor is not the delegation contract lead")
        profile = self._ledger.management_profiles.get(employee.id)
        if profile is None or not profile.active:
            return _denied("active management profile is missing")
        if profile.version != contract.management_profile_version:
            return _denied("management profile version is stale")
        team = self._ledger.teams.get(contract.team_id)
        if (
            team is None
            or team.status is not TeamStatus.ACTIVE
            or task.team_id != team.id
            or team.lead_employee_id != employee.id
        ):
            return _denied("active delegation Team is invalid")
        lead_membership = self._ledger.team_members.get(team.id, employee.id)
        if (
            lead_membership is None
            or lead_membership.left_at is not None
            or lead_membership.membership_role is not TeamMembershipRole.LEAD
        ):
            return _denied("active Team lead membership is missing")

        ceiling_layers = [self._global_limits, _profile_limits(profile)]
        if contract.parent_contract_task_id is not None:
            parent = self._ledger.delegation_contracts.active_for_task(
                contract.parent_contract_task_id
            )
            if parent is None:
                return _denied("active parent delegation contract is missing")
            ceiling_layers.append(_contract_limits(parent))
        ceiling = self.intersect(*ceiling_layers)
        if not _contract_within(contract, ceiling):
            return _denied("delegation contract exceeds an authority layer")
        effective = self.intersect(ceiling, _contract_limits(contract))
        if effective.max_depth <= 0:
            return _denied("delegation depth limit exceeded")

        if target is not None:
            if target.id == employee.id:
                return _denied("lead cannot assign delegated work to self")
            if target.reports_to != employee.id:
                return _denied("target is not a direct report")
            if target.status in {EmployeeStatus.PENDING, EmployeeStatus.TERMINATED}:
                return _denied("target employee is not active")
            if effective.allowed_professions and target.role not in effective.allowed_professions:
                return _denied("target profession is not allowed")
            if requested_mode is ExecutionMode.DELEGATION:
                target_profile = self._ledger.management_profiles.get(target.id)
                if (
                    not effective.can_subdelegate
                    or target_profile is None
                    or not target_profile.active
                    or not target_profile.can_lead
                    or not target_profile.can_subdelegate
                ):
                    return _denied("nested delegation is not granted")
        return AuthorizationResult(True, effective=effective)


def _profile_limits(profile: ManagementProfile) -> AuthorityLimits:
    return AuthorityLimits(
        max_depth=profile.max_delegation_depth,
        max_team_size=profile.max_team_size,
        spend_limit_cents=profile.spend_limit_cents,
        allowed_professions=frozenset(profile.allowed_professions),
        can_subdelegate=profile.can_subdelegate,
    )


def _contract_limits(contract: DelegationContract) -> AuthorityLimits:
    return AuthorityLimits(
        max_depth=contract.max_depth,
        max_team_size=contract.max_team_size,
        spend_limit_cents=contract.spend_limit_cents,
        can_subdelegate=contract.can_subdelegate,
    )


def _contract_within(contract: DelegationContract, ceiling: AuthorityLimits) -> bool:
    spend_within = ceiling.spend_limit_cents is None or (
        contract.spend_limit_cents is not None
        and contract.spend_limit_cents <= ceiling.spend_limit_cents
    )
    return (
        contract.max_depth <= ceiling.max_depth
        and contract.max_team_size <= ceiling.max_team_size
        and spend_within
        and (not contract.can_subdelegate or ceiling.can_subdelegate)
    )


def _denied(reason: str) -> AuthorizationResult:
    return AuthorizationResult(False, reason=reason)


__all__ = [
    "AuthorityIntersection",
    "AuthorityLimits",
    "AuthorizationResult",
    "EffectiveAuthority",
]