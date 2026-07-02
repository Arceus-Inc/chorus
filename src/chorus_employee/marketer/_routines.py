"""The Marketer's standing routines (design doc §13).

A role can carry recurring work; hiring a Marketer provisions these automatically (hire-time reconcile)
— no operator ``add_routine`` needed. ``MARKETER_ROUTINES`` is what
:func:`chorus_employee.marketer.marketer_plugin` hands to ``RolePlugin.declared_routines``.

The first routine is the **brand-drift scan**: a weekly read/report cadence that makes Mira a
campaigner rather than a pure responder (§13). It only reads shipped content against the voice spec and
flags drift — it mints work, it never trips a gate on its own (a proposed fix still stages for approval
like any other beat). Concurrency is ``coalesce`` so slow weeks never pile scans up.
"""

from __future__ import annotations

from chorus.ledger import RoutineConcurrency
from chorus.roles._routine_declaration import RoutineDeclaration

# Weekly brand-drift scan, filed every Monday 09:00.
# (Built-in plugins use the raw cron string — they load during chorus.roles init, before chorus.cron
# finishes importing, so they can't import the Schedule helper. Consumers registered after startup
# should prefer ``chorus.Schedule.weekly(Weekday.MONDAY, at="09:00")``.)
MARKETER_BRAND_DRIFT_SCAN = RoutineDeclaration(
    routine_key="marketer-brand-drift-scan",
    intent_template=(
        "Brand-drift scan: review the content that shipped since the last scan against "
        "`brand_spec.md` (the voice spec) — flag anything off-message, off-voice, or carrying an "
        "unsubstantiated claim, and note it in memory so it isn't repeated. Report and propose fixes "
        "only; do not publish or send."
    ),
    schedule="0 9 * * 1",  # == Schedule.weekly(Weekday.MONDAY, at="09:00")
    concurrency=RoutineConcurrency.COALESCE,
)

# Monthly content/GEO refresh, filed the 1st at 09:00. The second analytics-free routine (§13):
# owned content decays for generative-answer + search visibility as the category moves, so Mira
# re-scores what shipped on GEO/AEO + SEO craft (answer-first structure, schema, entity density,
# citation-readiness) and stages refreshes for the ones that drifted. Report/propose only — a
# refresh still stages for approval like any other beat; it never publishes on its own.
MARKETER_GEO_REFRESH = RoutineDeclaration(
    routine_key="marketer-geo-refresh",
    intent_template=(
        "Content/GEO refresh: re-score the owned content that shipped for GEO/AEO + SEO decay — "
        "answer-first structure, schema/entity density, and citation-readiness (would an AI answer "
        "engine cite it?). Load the `geo-aeo-seo` skill for the craft. Flag posts that have decayed "
        "or fallen behind the category, note why in memory, and propose refreshes. Report and propose "
        "only; do not publish or send — any refresh stages for approval like any other beat."
    ),
    schedule="0 9 1 * *",  # == Schedule.monthly(day=1, at="09:00")
    concurrency=RoutineConcurrency.COALESCE,
)

MARKETER_ROUTINES: tuple[RoutineDeclaration, ...] = (
    MARKETER_BRAND_DRIFT_SCAN,
    MARKETER_GEO_REFRESH,
)

__all__ = ["MARKETER_BRAND_DRIFT_SCAN", "MARKETER_GEO_REFRESH", "MARKETER_ROUTINES"]
