"""The Designer's standing routines (designer §14).

A role can carry recurring work; hiring a Designer provisions these automatically (hire-time reconcile) —
no operator ``add_routine`` needed. ``DESIGNER_ROUTINES`` is what
:func:`chorus_employee.designer.designer_plugin` hands to ``RolePlugin.declared_routines``.

The Designer is the Marketer's structural twin (designer §02): the Marketer's brand-drift scan
re-points to a **system-drift scan** (has the shipped UI drifted off the design system?), and its
GEO-refresh re-points to an **accessibility audit** (does the shipped UI still hold the a11y floor?).
Both are read/report cadences — they read shipped surfaces against ``DESIGN.md`` and flag drift; they
mint work but never trip a gate on their own (a proposed fix still stages for approval like any other
beat). Concurrency is ``coalesce`` so slow weeks never pile scans up.
"""

from __future__ import annotations

from chorus.ledger import RoutineConcurrency
from chorus.roles._routine_declaration import RoutineDeclaration

# Weekly system-drift scan, filed every Monday 09:00 (the brand-drift-scan twin).
# (Built-in plugins use the raw cron string — they load during chorus.roles init, before chorus.cron
# finishes importing, so they can't import the Schedule helper. Consumers registered after startup
# should prefer ``chorus.Schedule.weekly(Weekday.MONDAY, at="09:00")``.)
DESIGNER_SYSTEM_DRIFT_SCAN = RoutineDeclaration(
    routine_key="designer-system-drift-scan",
    intent_template=(
        "System-drift scan: review the UI/design specs that shipped since the last scan against "
        "`DESIGN.md` (the design system) — flag anything off-system (off-token colors, off-scale "
        "spacing, invented components that duplicate existing ones, contradictions of the documented "
        "scale), and note it in memory so it isn't repeated. Load the `design-system-authoring` and "
        "`token-scale-discipline` skills for the craft. Report and propose fixes only; do not ship, "
        "hand off, or trip any gate — a proposed fix stages for approval like any other beat."
    ),
    schedule="0 9 * * 1",  # == Schedule.weekly(Weekday.MONDAY, at="09:00")
    concurrency=RoutineConcurrency.COALESCE,
)

# Monthly accessibility audit, filed the 1st at 09:00 (the GEO-refresh twin). Owned UI decays for
# accessibility as it accretes features, so the Designer re-scores what shipped on the WCAG floor
# (contrast, keyboard path, focus order, aria, state coverage) and stages fixes for the surfaces that
# fell below it. Report/propose only — a fix still stages for approval like any other beat.
DESIGNER_ACCESSIBILITY_AUDIT = RoutineDeclaration(
    routine_key="designer-accessibility-audit",
    intent_template=(
        "Accessibility audit: re-score the UI/design specs that shipped for accessibility decay — "
        "color contrast against the DESIGN.md floor, keyboard reachability and focus order, aria "
        "semantics, and state coverage (empty / loading / error / disabled). Load the "
        "`wcag-conformance`, `color-contrast`, and `keyboard-and-focus` skills for the craft. Flag "
        "surfaces that fell below the floor, note why in memory, and propose fixes. Report and "
        "propose only; do not ship or hand off — any fix stages for approval like any other beat."
    ),
    schedule="0 9 1 * *",  # == Schedule.monthly(day=1, at="09:00")
    concurrency=RoutineConcurrency.COALESCE,
)

DESIGNER_ROUTINES: tuple[RoutineDeclaration, ...] = (
    DESIGNER_SYSTEM_DRIFT_SCAN,
    DESIGNER_ACCESSIBILITY_AUDIT,
)

__all__ = [
    "DESIGNER_ACCESSIBILITY_AUDIT",
    "DESIGNER_ROUTINES",
    "DESIGNER_SYSTEM_DRIFT_SCAN",
]
