"""The CEO's standing routines (spec 13 §5).

The executive-review loop is what makes the org move when nobody is watching — Paperclip's default
CEO cycle ("review what your executives are doing, check company metrics, reprioritize") adapted to
chorus's governance shape: the routine reads and proposes, it never hires, delegates, or spends on
its own — those actions stay behind the human gates. ``CEO_ROUTINES`` is what
:func:`chorus_employee.ceo.ceo_plugin` hands to ``RolePlugin.declared_routines`` and provisions on
hire, with no kernel change.
"""

from __future__ import annotations

from chorus.ledger import RoutineConcurrency
from chorus.roles._routine_declaration import RoutineDeclaration

# Hourly executive review, coalesced. The standing heartbeat of the org's apex: read the goal tree's
# health, the reports' recent beats and blockers, and spend vs budget; then re-prioritize and
# propose — a workforce plan where a goal lacks capacity, an unblock note where work is stuck.
# Report/propose only: materialization crosses the human approval door like any other proposal.
CEO_EXECUTIVE_REVIEW = RoutineDeclaration(
    routine_key="ceo-executive-review",
    intent_template=(
        "Executive review: your evidence base is `company_state.json` in your worktree — the "
        "mirrored ledger truth (goal tree, workforce with status and spend, open tasks). Read it "
        "and cite it. Assess each active goal's health (progressing, stalled, or unowned) from "
        "the open tasks under it; review your reports' recent work and blockers; compare each "
        "report's spend against their budget. Re-prioritize: note which goals deserve focus and "
        "which should pause. Where a goal lacks capacity, propose staffing via a workforce plan; "
        "where work is blocked, name the blocker and the unblocking step. Write the review as "
        "`directive.md`. Report and propose only — do not hire, delegate, or spend in this "
        "routine; every proposal crosses the human approval door."
    ),
    schedule="0 * * * *",  # == Schedule.hourly(at=":00")
    concurrency=RoutineConcurrency.COALESCE,
)

CEO_ROUTINES: tuple[RoutineDeclaration, ...] = (CEO_EXECUTIVE_REVIEW,)

__all__ = ["CEO_EXECUTIVE_REVIEW", "CEO_ROUTINES"]
