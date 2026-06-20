"""``org.routines`` — recurring work (spec 14 §5.4, spec 13).

Create a cron routine + its trigger, list/inspect them, pause/resume firing. The firing engine
(``fire_routine`` on the tick's CRON step) already exists; this is the reachability surface. Migrated
from the flat ``add_routine`` … verbs (spec 14 'migrate all').
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from chorus.cron import parse_cron, restore_routine, revise_routine
from chorus.ledger import (
    Routine,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineRevision,
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
        env: dict[str, str] | None = None,
        routine_key: str | None = None,
        timezone: str = "UTC",
    ) -> RoutineView:
        """Create a cron routine owned by ``employee``, seed its revision 1, and add its due trigger
        (spec 13 §3.1).

        ``employee`` is resolved by slug (fail-closed). The cron is parsed *before* any write, so a bad
        schedule leaves no orphan routine; the tick's CRON step picks it up from ``next_run_at``.
        Revision 1 snapshots the definition and becomes the live head a firing pins against."""
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
                env=env,
                routine_key=routine_key,
            )
        )
        rev1 = self._ledger.routine_revisions.append(
            RoutineRevision(
                id=f"rrev_{uuid.uuid4().hex[:12]}",
                routine_id=routine.id,
                revision_no=1,
                intent_template=intent_template,
                target=target,
                concurrency_policy=concurrency,
                catch_up_policy=catch_up,
                env=env,
                change_summary="created",
            )
        )
        self._ledger.routines.set_head(routine.id, rev1)
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

    def revise(
        self,
        routine_id: str,
        *,
        by: str,
        intent_template: str | None = None,
        target: RoutineTarget | None = None,
        concurrency: RoutineConcurrency | None = None,
        catch_up: RoutineCatchUp | None = None,
        change_summary: str | None = None,
    ) -> RoutineView:
        """Edit a routine: write a new head revision (spec 13 §2.2/§3.2). Only the supplied fields
        change. The reviser (resolved by slug) must be the routine's owner or the owner's manager."""
        revise_routine(
            self._ledger,
            routine_id=routine_id,
            revised_by=self._workforce.get(slugify(by)).id,
            intent_template=intent_template,
            target=target,
            concurrency=concurrency,
            catch_up=catch_up,
            change_summary=change_summary,
        )
        return self._inspector.routine(routine_id)

    def restore(self, routine_id: str, *, revision_no: int, by: str) -> RoutineView:
        """Roll a routine back to ``revision_no`` through a new head (spec 13 §3.2) — history is never
        mutated. The reviser (resolved by slug) must be the routine's owner or the owner's manager."""
        restore_routine(
            self._ledger,
            routine_id=routine_id,
            revision_no=revision_no,
            revised_by=self._workforce.get(slugify(by)).id,
        )
        return self._inspector.routine(routine_id)

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
