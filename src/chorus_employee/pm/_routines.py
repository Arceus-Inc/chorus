"""The PM's standing routines (spec 13 §4/§5).

A role can carry recurring work; hiring a PM provisions these automatically (hire-time reconcile) — no
operator ``add_routine`` needed. ``PM_ROUTINES`` is what :func:`chorus_employee.pm.pm_plugin` hands to
``RolePlugin.declared_routines``.
"""

from __future__ import annotations

from chorus.roles._routine_declaration import RoutineDeclaration
from chorus_employee.pm._brief import PM_PLAN_DOC

# A weekly planning review, filed every Monday 09:00.
PM_WEEKLY_PLANNING = RoutineDeclaration(
    routine_key="pm-weekly-planning-review",
    intent_template=(
        "Weekly planning review: assess the current goals and open work, then write or update the "
        f"plan in `{PM_PLAN_DOC}` with the priorities and next steps for the coming week."
    ),
    schedule="0 9 * * 1",  # 09:00 every Monday
)

PM_ROUTINES: tuple[RoutineDeclaration, ...] = (PM_WEEKLY_PLANNING,)

__all__ = ["PM_ROUTINES", "PM_WEEKLY_PLANNING"]
