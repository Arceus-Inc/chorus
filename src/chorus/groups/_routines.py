"""``org.routines`` — recurring work (spec 14 §5.4, spec 13).

Create a cron routine + its trigger, list/inspect them, pause/resume firing. The firing engine
(``fire_routine`` on the tick's CRON step) already exists; this is the reachability surface. Migrated
from the flat ``add_routine`` … verbs (spec 14 'migrate all').
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from chorus.cron import parse_cron
from chorus.ledger import (
    Routine,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineStatus,
    RoutineTarget,
    RoutineTrigger,
    SqliteLedger,
    TriggerKind,
)
from chorus.observability import LedgerInspector, RoutineView
from chorus.workforce import Workforce, slugify


class RoutinesFacade:
    """The ``org.routines`` surface — add / list / get / pause / resume."""

    def __init__(
        self, ledger: SqliteLedger, workforce: Workforce, inspector: LedgerInspector
    ) -> None:
        self._ledger = ledger
        self._workforce = workforce
        self._inspector = inspector

    def add(
        self,
        *,
        employee: str,
        intent_template: str,
        schedule: str,
        target: RoutineTarget = RoutineTarget.SPAWN_TASK,
        concurrency: RoutineConcurrency = RoutineConcurrency.COALESCE,
        catch_up: RoutineCatchUp = RoutineCatchUp.SKIP_MISSED,
        timezone: str = "UTC",
    ) -> RoutineView:
        """Create a cron routine owned by ``employee`` and its due trigger (spec 13 §3.1).

        ``employee`` is resolved by slug (fail-closed). The cron is parsed *before* any write, so a bad
        schedule leaves no orphan routine; the tick's CRON step picks it up from ``next_run_at``."""
        employee_id = self._workforce.get(slugify(employee)).id  # fail-closed on unknown
        next_run_at = parse_cron(schedule, base=datetime.now(UTC), timezone=timezone)
        routine = self._ledger.routines.create(
            Routine(
                id=f"routine_{uuid.uuid4().hex[:12]}",
                employee_id=employee_id,
                intent_template=intent_template,
                target=target,
                concurrency_policy=concurrency,
                catch_up_policy=catch_up,
            )
        )
        self._ledger.routine_triggers.create(
            RoutineTrigger(
                id=f"trig_{uuid.uuid4().hex[:12]}",
                routine_id=routine.id,
                kind=TriggerKind.CRON,
                cron_expression=schedule,
                timezone=timezone,
                next_run_at=next_run_at,
            )
        )
        return self._inspector.routine(routine.id)

    def list(self, *, employee: str | None = None) -> list[RoutineView]:
        """Every routine, optionally scoped to one employee (resolved by slug)."""
        employee_id = None if employee is None else self._workforce.get(slugify(employee)).id
        return self._inspector.list_routines(employee_id=employee_id)

    def get(self, routine_id: str) -> RoutineView:
        """One routine resolved for reading — definition + triggers + recent firings."""
        return self._inspector.routine(routine_id)

    def pause(self, routine_id: str) -> None:
        """Stop a routine from firing (it drops out of the tick's CRON scan)."""
        self._ledger.routines.set_status(routine_id, RoutineStatus.PAUSED)

    def resume(self, routine_id: str) -> None:
        """Resume a paused routine — its trigger's ``next_run_at`` starts selecting again."""
        self._ledger.routines.set_status(routine_id, RoutineStatus.ACTIVE)


__all__ = ["RoutinesFacade"]
