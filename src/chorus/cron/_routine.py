"""Cron / routines — a firing writes a task, never runs an agent (spec 03 §4).

A routine is a template + owner + schedule + policies. When a ``routine_trigger``
comes due, ``fire_routine`` resolves it into *ledger writes* (a new ``task``
assigned to the routine's employee, picked up by the normal wake flow) — it
never invokes an agent directly. Exact-once is the ``task_open_routine_uq`` index
plus the ``routine_run.idempotency_key`` (spec 01); the double-fire guard is the
conditional ``next_run_at`` UPDATE.

The cron *parser* is dream's (``dream.tasks._cron``, 5-field) — chorus does not
rewrite it; :func:`parse_cron` is the thin chorus-side adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RoutineTarget(StrEnum):
    """What a firing produces (spec 01 Cluster C ``routine.target``)."""

    SPAWN_TASK = "spawn_task"
    NEXT_BEAT = "next_beat"


class ConcurrencyPolicy(StrEnum):
    """How a firing behaves while a prior task is still live (spec 01)."""

    SKIP_IF_ACTIVE = "skip_if_active"
    COALESCE = "coalesce"
    ALWAYS = "always"


class CatchUpPolicy(StrEnum):
    """What happens to a missed window (spec 03 §4)."""

    SKIP_MISSED = "skip_missed"
    BACKFILL_ONE = "backfill_one"


class RoutineStatus(StrEnum):
    """Whether a routine is firing (spec 01 Cluster C ``routine.status``)."""

    ACTIVE = "active"
    PAUSED = "paused"


@dataclass(frozen=True)
class Routine:
    """A cron template + owner + policies (spec 01 Cluster C ``routine``/``routine_trigger``)."""

    id: str
    employee_id: str
    intent_template: str
    cron_expression: str
    timezone: str = "UTC"
    target: RoutineTarget = RoutineTarget.SPAWN_TASK
    concurrency_policy: ConcurrencyPolicy = ConcurrencyPolicy.SKIP_IF_ACTIVE
    catch_up_policy: CatchUpPolicy = CatchUpPolicy.SKIP_MISSED
    status: RoutineStatus = RoutineStatus.ACTIVE
    goal_id: str | None = None
    parent_task_id: str | None = None
    next_run_at: datetime | None = None
    last_fired_at: datetime | None = None


def parse_cron(expression: str, *, base: datetime, timezone: str = "UTC") -> datetime:
    """Return the next fire time strictly after ``base`` for a 5-field cron expr.

    Thin adapter over dream's canonical cron parser (``dream.tasks._cron``,
    spec 03 §4); the scaffold falls back to ``croniter``. The conditional
    ``next_run_at`` UPDATE (spec 01) — not this function — is what guards against
    double-firing the same edge across ticks/processes.
    """
    raise NotImplementedError("spec 03 §4: delegate to dream's 5-field cron parser")


__all__ = [
    "CatchUpPolicy",
    "ConcurrencyPolicy",
    "Routine",
    "RoutineStatus",
    "RoutineTarget",
    "parse_cron",
]
