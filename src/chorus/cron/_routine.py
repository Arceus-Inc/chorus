"""The cron parser adapter (spec 03 §4) — the one thing the firing engine borrows from dream.

A routine's data model (``Routine`` / ``RoutineTrigger`` / ``RoutineRun`` + the
``RoutineConcurrency`` / ``RoutineCatchUp`` / ``RoutineTarget`` / ``RoutineStatus`` enums) is the
canonical ledger model in :mod:`chorus.ledger._models`; the firing logic is
:func:`chorus.cron._fire.fire_routine`. This module holds only :func:`parse_cron`, the thin adapter
over dream's 5-field parser — chorus does not rewrite cron math.
"""

from __future__ import annotations

from datetime import datetime


def parse_cron(expression: str, *, base: datetime, timezone: str = "UTC") -> datetime:
    """Return the next fire time strictly after ``base`` for a 5-field cron expr.

    Thin adapter over dream's canonical cron parser (``dream.tasks._cron``, spec 03 §4); the scaffold
    falls back to ``croniter``. The conditional ``next_run_at`` UPDATE (spec 01) — not this function —
    is what guards against double-firing the same edge across ticks/processes.
    """
    from dream.tasks._cron import next_run_time

    return next_run_time(expression, base=base, tz=timezone)


__all__ = ["parse_cron"]
