"""The ``Chorus`` facade — the composition root (spec 10 §1).

One object, built once, wires the concrete backends and is the **only** thing
that imports dream (the "wiring"). ``build()`` news-up the ``SqliteLedger``, the
``GitWorkforce``, the ``GitMemoryStore`` + ``AppendOnlyMemoryWriter``, the dream
board ``ClaimManager``, the ``Scheduler``, the ``EventBus``, and the
``Inspector``, and injects them — nothing else creates concrete classes.

A consumer (an ``examples/`` file, or Arceus) only touches the public methods
below; the behavior is stubbed pending implementation (M1+, spec 11 build plan).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from chorus.events import Event
from chorus.heartbeat import Scheduler, TickReport
from chorus.ledger import SqliteLedger, Task
from chorus.memory import AppendOnlyMemoryWriter
from chorus.observability import EventBus, LedgerInspector, TaskView, WorkforceStatus
from chorus.outcomes import Verifier
from chorus.roles import RolePlugin, default_roles
from chorus.workforce import Employee, GitWorkforce


@dataclass(frozen=True)
class Caps:
    """Workforce-wide governance caps (spec 03 §5, spec 06 §4)."""

    max_concurrent_runs: int = 4
    request_depth_cap: int = 5
    tick_interval_s: float = 1.0


class Chorus:
    """The org kernel facade (spec 10 §1)."""

    def __init__(
        self,
        *,
        ledger: SqliteLedger,
        workforce: GitWorkforce,
        memory_writer: AppendOnlyMemoryWriter,
        scheduler: Scheduler,
        event_bus: EventBus,
        inspector: LedgerInspector,
        dream: Any,
        roles: dict[str, RolePlugin],
        caps: Caps,
    ) -> None:
        self._ledger = ledger
        self._workforce = workforce
        self._memory_writer = memory_writer
        self._scheduler = scheduler
        self._event_bus = event_bus
        self._inspector = inspector
        self._dream = dream
        self._roles = roles
        self._caps = caps

    # -- construction ---------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        db_path: str,
        org_repo: str,
        memory_repo: str,
        dream: Any,
        roles: Sequence[RolePlugin] | None = None,
        caps: Caps | None = None,
    ) -> Chorus:
        """The composition root — wire the concrete backends and inject them (spec 10 §1).

        ``dream`` is the dream SDK facade/module — the single seam chorus calls
        for the planner→sprint→evaluator loop. ``roles`` defaults to
        :func:`chorus.roles.default_roles`; extra roles register through the same
        validated path (spec 09 §1).
        """
        the_caps = caps or Caps()
        registry = {p.name: p for p in (roles if roles is not None else default_roles())}
        return cls(
            ledger=SqliteLedger.open(db_path),
            workforce=GitWorkforce(org_repo),
            memory_writer=AppendOnlyMemoryWriter(memory_repo),
            scheduler=Scheduler(
                tick_interval_s=the_caps.tick_interval_s,
                max_concurrent_runs=the_caps.max_concurrent_runs,
            ),
            event_bus=EventBus(),
            inspector=LedgerInspector(),
            dream=dream,
            roles=registry,
            caps=the_caps,
        )

    # -- intake (horizon handoff seam, spec 10 §5) ----------------------------

    def submit(
        self,
        intent: str,
        *,
        assignee: str | None = None,
        dod: Verifier | None = None,
        depends_on: Sequence[str] = (),
    ) -> Task:
        """Create a flat ``depth=0`` intake task (spec 10 §5).

        The reserved intake seam: today the stub; when horizon ships it becomes
        the writer of intake and drives this same path. chorus never grows a
        second intake door.
        """
        raise NotImplementedError("spec 10 §5: intake stub → task(depth=0)")

    # -- the heartbeat (spec 03) ----------------------------------------------

    async def tick(self) -> TickReport:
        """One kernel pulse (spec 03 §3)."""
        raise NotImplementedError("spec 03 §3: delegate to Scheduler.tick(now)")

    async def run_forever(self, interval_s: float = 2.0) -> None:
        """Drive ticks until cancelled (spec 03 §3)."""
        raise NotImplementedError("spec 03 §3: loop tick() at interval, jittered in Arceus")

    # -- org as data (spec 06 §3) ---------------------------------------------

    def hire(self, *, name: str, role: str, reports_to: str | None = None) -> Employee:
        """Add an employee (a data edit, not a process spawn) (spec 06 §3)."""
        raise NotImplementedError("spec 06 §3: validate role + org chain, then GitWorkforce.hire")

    def terminate(self, employee_id: str) -> None:
        """Irreversibly terminate an employee; cancel its in-flight work (spec 06 §3)."""
        raise NotImplementedError("spec 06 §3: irreversible terminate + cancel runs")

    def register_role(self, plugin: RolePlugin, *, replace: bool = False) -> None:
        """Register a role plugin — fail-closed + idempotent (spec 09 §1)."""
        raise NotImplementedError("spec 09 §1: validate → register → freeze-at-first-use")

    # -- cron (spec 03 §4) ----------------------------------------------------

    def add_routine(
        self,
        *,
        employee: str,
        intent_template: str,
        schedule: str,
        target: str = "spawn_task",
    ) -> Any:
        """Add a cron routine owned by ``employee`` (spec 03 §4)."""
        raise NotImplementedError("spec 03 §4: persist routine + trigger")

    # -- inspection (read model, spec 08) -------------------------------------

    def status(self) -> WorkforceStatus:
        """The company at a glance (spec 08 §2)."""
        raise NotImplementedError("spec 08 §3: delegate to Inspector.status")

    def task(self, task_id: str) -> TaskView:
        """One task, resolved for reading (spec 10 §1)."""
        raise NotImplementedError("spec 08 §3: delegate to Inspector.task")

    def events(self, *, after: str | None = None) -> Iterator[Event]:
        """Replay the event stream from ``after`` (spec 08 §1)."""
        raise NotImplementedError("spec 08 §1: delegate to EventBus.replay")

    def stuck(self) -> list[TaskView]:
        """The blocked inbox — stuck tasks, ranked (spec 08 §2)."""
        raise NotImplementedError("spec 08 §2: delegate to Inspector.stuck")


__all__ = [
    "Caps",
    "Chorus",
]
