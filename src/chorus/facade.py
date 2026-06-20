"""The ``Chorus`` facade — the composition root (spec 10 §1).

One object, built once, wires the concrete backends and is the **only** thing
that imports dream (the "wiring"). ``build()`` news-up the ``SqliteLedger``, the
``LedgerWorkforce`` (the single live org store), the ``GitMemoryStore`` +
``AppendOnlyMemoryWriter``, the dream board ``ClaimManager``, the ``Scheduler``,
the ``EventBus``, and the ``Inspector``, and injects them — nothing else creates
concrete classes.

A consumer (an ``examples/`` file, or Arceus) only touches the public methods
below; the behavior is stubbed pending implementation (M1+, spec 11 build plan).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from chorus.budgets import BudgetEnforcer
from chorus.errors import OrgInvariantViolation
from chorus.governance import GovernancePolicy
from chorus.groups import (
    BudgetsFacade,
    DodFacade,
    GovernanceFacade,
    InspectFacade,
    RoutinesFacade,
    TrustFacade,
    WorkforceFacade,
)
from chorus.heartbeat import (
    BeatRunner,
    BeatRunnerFor,
    BeatRunnerForFn,
    Scheduler,
    TickReport,
    Wake,
    runner_from,
)
from chorus.ledger import (
    Message,
    SqliteLedger,
    Task,
    TaskPriority,
)
from chorus.lifecycle import (
    DEFAULT_REQUEST_DEPTH_CAP,
    assign_task,
    deliver_message,
)
from chorus.memory import AppendOnlyMemoryWriter
from chorus.observability import EventBus, LedgerInspector, WorkforceStatus
from chorus.outcomes import LanderRegistry, Verifier
from chorus.roles import RolePlugin, RoleRegistry, default_roles
from chorus.trust import TrustPreset
from chorus.workforce import (
    Employee,
    LedgerWorkforce,
    Workforce,
    slugify,
)


@dataclass(frozen=True)
class Caps:
    """Workforce-wide governance caps (spec 03 §5, spec 06 §4)."""

    max_concurrent_runs: int = 4
    request_depth_cap: int = DEFAULT_REQUEST_DEPTH_CAP
    tick_interval_s: float = 1.0


class Chorus:
    """The org kernel facade (spec 10 §1)."""

    def __init__(
        self,
        *,
        ledger: SqliteLedger,
        workforce: Workforce,
        memory_writer: AppendOnlyMemoryWriter,
        scheduler: Scheduler,
        event_bus: EventBus,
        inspector: LedgerInspector,
        dream: Any,
        roles: RoleRegistry,
        caps: Caps,
        governance_policy: GovernancePolicy | None = None,
        company_id: str = "company",
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
        self._governance_policy = governance_policy or GovernancePolicy()
        # Low-level grouped surfaces (spec 14 §2.2) — built once over the same backends.
        self._inspect = InspectFacade(inspector, event_bus)
        self._governance = GovernanceFacade(ledger, workforce, roles, self._governance_policy)
        self._budgets = BudgetsFacade(ledger, company_id=company_id)
        self._trust = TrustFacade(ledger)
        self._routines = RoutinesFacade(ledger, workforce, inspector)
        self._workforce_grp = WorkforceFacade(workforce, roles)
        self._dod = DodFacade(ledger)

    # -- construction ---------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        db_path: str | None = None,
        ledger: SqliteLedger | None = None,
        org_repo: str,
        memory_repo: str,
        dream: Any,
        beat_runner: BeatRunner | None = None,
        beat_runner_for: BeatRunnerFor | BeatRunnerForFn | None = None,
        landers: LanderRegistry | None = None,
        roles: Sequence[RolePlugin] | None = None,
        caps: Caps | None = None,
        company_id: str = "company",
    ) -> Chorus:
        """The composition root — wire the concrete backends and inject them (spec 10 §1).

        ``dream`` is the dream SDK facade/module — the single seam chorus calls
        for the planner→sprint→evaluator loop. ``beat_runner`` is the concrete dream
        adapter the scheduler runs each beat through; until it is supplied the kernel
        ticks (recover/cron/monitors/dispatch) but cannot execute a beat. ``landers`` is the
        symmetric *landing* seam — the registry the kernel lands a passed beat's deliverable
        through (the consumer passes ``factory.landers``); unset, a passed beat still completes
        but records no role artifact. Pass **exactly one** of ``db_path`` (open a fresh store) or
        ``ledger`` (share an already-open store with the harness factory, so a reviewer's verdict
        and the factory's capability tools land in *one* ledger, not two). ``roles`` defaults to
        :func:`chorus.roles.default_roles`; extra roles register through the same validated path
        (spec 09 §1).
        """
        if db_path is not None and ledger is not None:
            raise ValueError("provide either db_path or ledger, not both")
        the_caps = caps or Caps()
        registry = RoleRegistry.from_plugins(roles if roles is not None else default_roles())
        # The seam accepts either the resolver object or its bound method (the §0 front-door form,
        # ``beat_runner_for=factory.runner_for``) — a bare callable is wrapped to the protocol.
        resolved_runner_for: BeatRunnerFor | None
        if beat_runner_for is None or isinstance(beat_runner_for, BeatRunnerFor):
            resolved_runner_for = beat_runner_for
        else:
            resolved_runner_for = runner_from(beat_runner_for)
        if ledger is not None:
            store = ledger
        elif db_path is not None:
            store = SqliteLedger.open(db_path)
        else:
            raise ValueError("provide exactly one of db_path or ledger")
        # The live workforce is the ledger employee table — the single source of truth every
        # assignment FK points at (spec 06 §3). ``org_repo`` is the portable git-markdown
        # export/import location (spec 09 §3, the GitWorkforce codec), not a second live store.
        workforce = LedgerWorkforce(store.employees)
        event_bus = EventBus()
        scheduler = Scheduler(
            tick_interval_s=the_caps.tick_interval_s,
            max_concurrent_runs=the_caps.max_concurrent_runs,
            ledger=store,
            workforce=workforce,
            beat_runner=beat_runner,
            beat_runner_for=resolved_runner_for,  # role-faithful per-employee runners (spec 06 §2)
            event_bus=event_bus,
            # budgets are inert until a policy is created — injecting the enforcer just arms the gates
            budget_enforcer=BudgetEnforcer(store, company_id=company_id),
            roles=registry,  # a task inherits its assignee role's DoD at intake (spec 04 §1 / 06 §2)
            landers=landers,  # the landing seam — a passed beat lands its role artifact (spec 04 §2)
        )
        return cls(
            ledger=store,
            workforce=workforce,
            memory_writer=AppendOnlyMemoryWriter(memory_repo),
            scheduler=scheduler,
            event_bus=event_bus,
            inspector=LedgerInspector(store),
            dream=dream,
            roles=registry,
            caps=the_caps,
            company_id=company_id,
        )

    # -- intake (horizon handoff seam, spec 10 §5) ----------------------------

    def submit(
        self,
        intent: str,
        *,
        assignee: str | None = None,
        dod: Verifier | None = None,
        depends_on: Sequence[str] = (),
        priority: TaskPriority = TaskPriority.MEDIUM,
        trust_preset: TrustPreset | None = None,
        trust_boundary: dict[str, object] | None = None,
    ) -> Task:
        """Create a flat ``depth=0`` intake task, optionally wired in one call (spec 10 §5 / 14 §3).

        The high-level front door: ``submit("build a login page", assignee="moe")`` creates the task,
        sets its DoD + dependencies if given, and hands it to its owner (``backlog`` → ``todo`` + a
        wake). ``assignee`` is resolved by slug and fail-closed (an unknown employee raises
        ``UnknownEmployee`` before anything is written). The reserved intake seam: when horizon ships
        it drives this same path — chorus never grows a second intake door.
        """
        employee_id = self._workforce.get(slugify(assignee)).id if assignee is not None else None
        task = self._ledger.tasks.submit(
            Task(
                id=f"task_{uuid.uuid4().hex[:12]}",
                intent=intent,
                priority=priority,
                trust_preset=trust_preset.value if trust_preset is not None else None,
                trust_boundary=trust_boundary,
            )
        )
        if dod is not None:
            self._ledger.dod.create(task.id, dod)
        for blocker in depends_on:
            self._ledger.dependencies.add(task.id, blocker)
        if employee_id is not None:
            assign_task(self._ledger, task.id, employee_id)
        return task

    def assign(
        self, task_id: str, employee_id: str, *, assigned_by: str | None = None
    ) -> Wake | None:
        """Assign a task to an employee and wake them (``task_assigned``, spec 03 §2).

        The async manager→report handoff: sets the owner (``backlog`` → ``todo``), enqueues the
        wake the next tick dispatches, and audits the handoff. ``None`` if the task is unknown or
        already terminal.
        """
        return assign_task(self._ledger, task_id, employee_id, assigned_by=assigned_by)

    def send_message(self, message: Message) -> Wake:
        """Deliver a mailbox message and wake the recipient (``message``, spec 03 §2)."""
        return deliver_message(self._ledger, message)

    # -- the heartbeat (spec 03) ----------------------------------------------

    async def tick(self) -> TickReport:
        """One kernel pulse, stamped with the kernel clock (spec 03 §3)."""
        return await self._scheduler.tick_once()

    async def drain(self) -> None:
        """Await every beat this pulse dispatched (spec 03 §3).

        :meth:`tick` returns as soon as it has *dispatched* — the beats run on. ``await org.tick();
        await org.drain()`` is the deterministic step: it runs one pulse and blocks until that pulse's
        beats finish, so a caller can advance a multi-beat flow (build → review → integrate) one
        settled step at a time. :meth:`run_forever` does this for every pulse internally.
        """
        await self._scheduler.drain()

    async def run_forever(self) -> None:
        """Run the heartbeat until :meth:`stop` (or cancellation), draining beats on exit (spec 03 §3)."""
        await self._scheduler.run()

    def stop(self) -> None:
        """Signal :meth:`run_forever` to exit after the current pulse (spec 03 §3)."""
        self._scheduler.stop()

    # -- org as data (spec 06 §3) ---------------------------------------------

    def hire(self, *, name: str, role: str, reports_to: str | None = None) -> Employee:
        """Add an employee (a data edit, not a process spawn) (spec 06 §3).

        Validates the role is registered, then delegates the org-chain invariants (unknown
        ``reports_to``, self-edge, duplicate slug) to the workforce.
        """
        if role not in self._roles:
            raise OrgInvariantViolation(f"unknown role {role!r}")
        return self._workforce.hire(name=name, role=role, reports_to=reports_to)

    @property
    def routines(self) -> RoutinesFacade:
        """``org.routines`` — recurring work: add / list / get / pause / resume (spec 13)."""
        return self._routines

    @property
    def workforce(self) -> WorkforceFacade:
        """``org.workforce`` — register_role + portable export/import_ (spec 09)."""
        return self._workforce_grp

    @property
    def dod(self) -> DodFacade:
        """``org.dod`` — revise a task's Definition of Done (spec 04 §1)."""
        return self._dod

    @property
    def governance(self) -> GovernanceFacade:
        """``org.governance`` — request/open gates, resolve them (approve/deny), read the open inbox."""
        return self._governance

    @property
    def budgets(self) -> BudgetsFacade:
        """``org.budgets`` — set token-salary caps, raise_/dismiss after a breach (spec 04 §3)."""
        return self._budgets

    @property
    def trust(self) -> TrustFacade:
        """``org.trust`` — set a task's trust preset + boundary (spec 04 §4)."""
        return self._trust

    def terminate(self, employee_id: str) -> None:
        """Irreversibly terminate an employee; cancel its in-flight work (spec 06 §3).

        The terminate is the source of truth (irreversible, root-protected); cancelling the
        in-flight run and dropping queued wakes stops the scheduler dispatching the dead identity.
        """
        self._workforce.terminate(employee_id)
        self._ledger.runs.cancel_running(employee_id=employee_id)
        self._ledger.wakes.drop_queued(employee_id=employee_id)

    # -- inspection (read model, spec 08 / spec 14 §4) ------------------------

    def status(self) -> WorkforceStatus:
        """The company at a glance — the high-level glance (spec 08 §2). Detail is ``inspect``."""
        return self._inspector.status()

    @property
    def inspect(self) -> InspectFacade:
        """``org.inspect`` — detailed reads: task / stuck / events / scrum_packet / org_report."""
        return self._inspect


__all__ = [
    "Caps",
    "Chorus",
]
