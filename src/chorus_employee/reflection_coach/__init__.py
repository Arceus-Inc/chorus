"""The managed Reflection Coach identity and its paused routine installer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from chorus_employee.reflection_coach._plugin import reflection_coach_plugin
from chorus_employee.reflection_coach._routines import (
    REFLECTION_COACH_ROUTINE,
    REFLECTION_COACH_ROUTINES,
)

REFLECTION_COACH_EMPLOYEE_ID = "reflection-coach"

if TYPE_CHECKING:
    from chorus.cron import ReconcileResult
    from chorus.ledger import Ledger
    from chorus.roles._registry import RoleRegistry
    from chorus.workforce import Employee, Workforce


@dataclass(frozen=True)
class RecentAgentReflectionPolicy:
    """The managed boundary that excludes the coach from its own review population."""

    excluded_employee_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.excluded_employee_ids:
            raise ValueError("reflection policy must exclude at least one employee")
        if any(not employee_id.strip() for employee_id in self.excluded_employee_ids):
            raise ValueError("reflection policy exclusions must not be blank")
        if len(set(self.excluded_employee_ids)) != len(self.excluded_employee_ids):
            raise ValueError("reflection policy exclusions must be unique")

    def allows(self, employee_id: str) -> bool:
        """Whether a candidate may be coached by this routine."""
        return employee_id not in self.excluded_employee_ids


@dataclass(frozen=True)
class ReflectionCoachConfiguration:
    """Validated identity and targeting boundary for the managed coach."""

    employee_id: str
    targeting_policy: RecentAgentReflectionPolicy

    def __post_init__(self) -> None:
        if not self.employee_id.strip():
            raise ValueError("reflection coach employee_id must not be blank")
        if self.targeting_policy.allows(self.employee_id):
            raise ValueError("reflection coach configuration must exclude its own employee")


REFLECTION_COACH_CONFIGURATION = ReflectionCoachConfiguration(
    employee_id=REFLECTION_COACH_EMPLOYEE_ID,
    targeting_policy=RecentAgentReflectionPolicy((REFLECTION_COACH_EMPLOYEE_ID,)),
)


@dataclass(frozen=True)
class ReflectionCoachInstallation:
    """The installed coach identity, self-exclusion policy, and reconcile outcome."""

    employee: Employee
    targeting_policy: RecentAgentReflectionPolicy
    reconciliation: ReconcileResult


def install_reflection_coach(
    *, ledger: Ledger, workforce: Workforce, roles: RoleRegistry
) -> ReflectionCoachInstallation:
    """Install the singleton coach and reconcile its paused routine without reactivating it."""
    from chorus_employee.reflection_coach._installer import (
        install_reflection_coach as provision,
    )

    employee, reconciliation = provision(ledger=ledger, workforce=workforce, roles=roles)
    return ReflectionCoachInstallation(
        employee=employee,
        targeting_policy=REFLECTION_COACH_CONFIGURATION.targeting_policy,
        reconciliation=reconciliation,
    )


__all__ = [
    "REFLECTION_COACH_CONFIGURATION",
    "REFLECTION_COACH_EMPLOYEE_ID",
    "REFLECTION_COACH_ROUTINE",
    "REFLECTION_COACH_ROUTINES",
    "RecentAgentReflectionPolicy",
    "ReflectionCoachConfiguration",
    "ReflectionCoachInstallation",
    "install_reflection_coach",
    "reflection_coach_plugin",
]
