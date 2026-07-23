"""The PM's standing routines (spec 13 §4/§5).

A role can carry recurring work; hiring a PM provisions these automatically (hire-time reconcile) — no
operator ``add_routine`` needed. ``PM_ROUTINES`` is what :func:`chorus_employee.pm.pm_plugin` hands to
``RolePlugin.declared_routines``.
"""

from __future__ import annotations

from chorus.roles._routine_declaration import RoutineDeclaration
from chorus_employee.pm._brief import PM_PLAN_DOC

# A weekly planning review, filed every Monday 09:00.
# (Built-in plugins use the raw cron string — they load during chorus.roles init, before chorus.cron
# finishes importing, so they can't import the Schedule helper. Consumers and plugins registered after
# startup should prefer ``chorus.Schedule.weekly(Weekday.MONDAY, at="09:00")``.)
# The intent asks for exactly what the PM's grounding floor verifies (._dod): the plan doc AND a
# recorded, cited decision — a routine whose intent under-specifies its own DoD can never pass.
PM_WEEKLY_PLANNING = RoutineDeclaration(
    routine_key="pm-weekly-planning-review",
    intent_template=(
        "Weekly planning review: assess the current goals and open work, then write or update the "
        f"plan in `{PM_PLAN_DOC}` with the priorities and next steps for the coming week. Record "
        "the week's top-priority call with the `record_decision` tool — state the chosen option, "
        "your confidence, the outcome metric, and cite at least one source (a repo artifact path "
        "or URL you actually consulted); the recorded decision is this routine's deliverable "
        "alongside the plan."
    ),
    schedule="0 9 * * 1",  # == Schedule.weekly(Weekday.MONDAY, at="09:00")
)

PM_ROUTINES: tuple[RoutineDeclaration, ...] = (PM_WEEKLY_PLANNING,)

__all__ = ["PM_ROUTINES", "PM_WEEKLY_PLANNING"]
