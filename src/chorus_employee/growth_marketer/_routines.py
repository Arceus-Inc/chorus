"""The Growth Marketer's standing routines — the clock that makes her a loop (spec GM §11).

Mira ships these with her plugin; hiring her provisions them automatically (hire-time reconcile) — no
operator ``add_routine`` and no kernel change. ``GROWTH_MARKETER_ROUTINES`` is what
:func:`chorus_employee.growth_marketer.growth_marketer_plugin` hands to ``RolePlugin.declared_routines``.

Two cron routines are declared here. The third edge of the loop — the *on-signal wake* (Monitor emits
a wake when the metric crosses a threshold) — is **not** a cron declaration: today's routines are
cron-only, and that internal metric-threshold wake is minted by Mira's own Monitor Agent via a
next-beat/CRON_DUE-style wake, so it needs no HTTP listener (spec GM §11).
"""

from __future__ import annotations

from chorus.ledger import RoutineConcurrency
from chorus.roles._routine_declaration import RoutineDeclaration

# Built-in plugins use the raw cron string (they load during chorus.roles init, before chorus.cron
# finishes importing). Consumers registered after startup may prefer ``chorus.Schedule.weekly(...)``.

# Mon 09:00 — review the activation funnel, propose & prioritize the week's experiments.
GROWTH_WEEKLY_FUNNEL_REVIEW = RoutineDeclaration(
    routine_key="growth-weekly-funnel-review",
    intent_template=(
        "Weekly funnel review: assess the activation funnel and open experiments, then propose and "
        "prioritize this week's experiments and write the campaign brief."
    ),
    schedule="0 9 * * 1",  # == Schedule.weekly(Weekday.MONDAY, at="09:00")
    concurrency=RoutineConcurrency.COALESCE,
)

# Daily 08:00 — watch live experiments: early-stop losers, flag regressions.
GROWTH_DAILY_EXPERIMENT_WATCH = RoutineDeclaration(
    routine_key="growth-daily-experiment-watch",
    intent_template=(
        "Daily experiment watch: check live experiments — early-stop losers, flag regressions, and "
        "emit the next signal if the metric crossed a threshold."
    ),
    schedule="0 8 * * *",  # == Schedule.daily(at="08:00")
    concurrency=RoutineConcurrency.SKIP_IF_ACTIVE,
)

GROWTH_MARKETER_ROUTINES: tuple[RoutineDeclaration, ...] = (
    GROWTH_WEEKLY_FUNNEL_REVIEW,
    GROWTH_DAILY_EXPERIMENT_WATCH,
)

__all__ = [
    "GROWTH_DAILY_EXPERIMENT_WATCH",
    "GROWTH_MARKETER_ROUTINES",
    "GROWTH_WEEKLY_FUNNEL_REVIEW",
]
