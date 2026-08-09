"""The Reflection Coach's managed, initially paused recent-agent review."""

from __future__ import annotations

from chorus.ledger import RoutineStatus
from chorus.roles._routine_declaration import RoutineDeclaration

REFLECTION_COACH_ROUTINE = RoutineDeclaration(
    routine_key="reflection-coach-recent-agent-review",
    intent_template=(
        "Recent-agent reflection: review recent work from other agents only; never target or coach "
        "yourself. Perform evidence clustering before reaching conclusions. Propose only minimal "
        "reviewable diffs and representative-success replay checks. This is "
        "proposal-only work: never silently apply, merge, or ship a change."
    ),
    schedule="0 9 * * 1",
    initial_status=RoutineStatus.PAUSED,
)

REFLECTION_COACH_ROUTINES: tuple[RoutineDeclaration, ...] = (REFLECTION_COACH_ROUTINE,)

__all__ = ["REFLECTION_COACH_ROUTINE", "REFLECTION_COACH_ROUTINES"]
