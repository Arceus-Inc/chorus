"""Transactional, idempotent provisioning for the managed Reflection Coach."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chorus.cron import reconcile_declared_routines
from chorus.errors import OrgInvariantViolation, UnknownEmployee
from chorus.ledger import Ledger, LedgerIntegrityError
from chorus.roles._registry import RoleRegistry
from chorus.workforce import Workforce
from chorus_employee.reflection_coach._plugin import reflection_coach_plugin
from chorus_employee.reflection_coach._routines import REFLECTION_COACH_ROUTINES

if TYPE_CHECKING:
    from chorus.cron import ReconcileResult
    from chorus.workforce import Employee

_REFLECTION_COACH_ROLE = "reflection_coach"
_REFLECTION_COACH_NAME = "Reflection Coach"


def install_reflection_coach(
    *, ledger: Ledger, workforce: Workforce, roles: RoleRegistry
) -> tuple[Employee, ReconcileResult]:
    """Provision the singleton coach and its paused routine as one ledger transaction."""
    from chorus_employee.reflection_coach import REFLECTION_COACH_CONFIGURATION

    roles.register(reflection_coach_plugin())
    with ledger.transaction():
        try:
            employee = workforce.get(REFLECTION_COACH_CONFIGURATION.employee_id)
        except UnknownEmployee:
            try:
                employee = workforce.hire(name=_REFLECTION_COACH_NAME, role=_REFLECTION_COACH_ROLE)
            except LedgerIntegrityError:
                employee = workforce.get(REFLECTION_COACH_CONFIGURATION.employee_id)
        if employee.role != _REFLECTION_COACH_ROLE:
            raise OrgInvariantViolation(
                f"managed Reflection Coach id is occupied by role {employee.role!r}"
            )
        reconciliation = reconcile_declared_routines(
            ledger,
            employee_id=employee.id,
            declarations=REFLECTION_COACH_ROUTINES,
        )
    return employee, reconciliation


__all__ = ["install_reflection_coach"]
