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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from chorus.budgets import BudgetEnforcer
from chorus.errors import OrgInvariantViolation
from chorus.events import Event
from chorus.governance import GovernancePolicy, GovernanceResolver
from chorus.heartbeat import BeatRunner, BeatRunnerFor, Scheduler, TickReport, Wake
from chorus.ledger import (
    Approval,
    ApprovalAction,
    ApprovalSubjectKind,
    BudgetPolicy,
    BudgetScope,
    Message,
    SqliteLedger,
    Task,
)
from chorus.lifecycle import DEFAULT_REQUEST_DEPTH_CAP, assign_task, deliver_message
from chorus.memory import AppendOnlyMemoryWriter
from chorus.observability import EventBus, LedgerInspector, TaskView, WorkforceStatus
from chorus.outcomes import Verifier
from chorus.roles import RolePlugin, RoleRegistry, default_roles
from chorus.workforce import (
    Employee,
    EmployeeStatus,
    GitWorkforce,
    LedgerWorkforce,
    Workforce,
    copy_org,
)


@dataclass(frozen=True)
class Caps:
    """Workforce-wide governance caps (spec 03 §5, spec 06 §4)."""

    max_concurrent_runs: int = 4
    request_depth_cap: int = DEFAULT_REQUEST_DEPTH_CAP
    tick_interval_s: float = 1.0


@dataclass(frozen=True)
class HireRequest:
    """The result of :meth:`Chorus.request_hire` (spec 04 §5 ``hire_employee``).

    ``approval`` is the pending ``hire_employee`` gate when the policy required sign-off, else ``None``
    (the employee was hired directly and is already active)."""

    employee: Employee
    approval: Approval | None


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

    # -- construction ---------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        db_path: str,
        org_repo: str,
        memory_repo: str,
        dream: Any,
        beat_runner: BeatRunner | None = None,
        beat_runner_for: BeatRunnerFor | None = None,
        roles: Sequence[RolePlugin] | None = None,
        caps: Caps | None = None,
        company_id: str = "company",
    ) -> Chorus:
        """The composition root — wire the concrete backends and inject them (spec 10 §1).

        ``dream`` is the dream SDK facade/module — the single seam chorus calls
        for the planner→sprint→evaluator loop. ``beat_runner`` is the concrete dream
        adapter the scheduler runs each beat through; until it is supplied the kernel
        ticks (recover/cron/monitors/dispatch) but cannot execute a beat. ``roles``
        defaults to :func:`chorus.roles.default_roles`; extra roles register through
        the same validated path (spec 09 §1).
        """
        the_caps = caps or Caps()
        registry = RoleRegistry.from_plugins(roles if roles is not None else default_roles())
        ledger = SqliteLedger.open(db_path)
        # The live workforce is the ledger employee table — the single source of truth every
        # assignment FK points at (spec 06 §3). ``org_repo`` is the portable git-markdown
        # export/import location (spec 09 §3, the GitWorkforce codec), not a second live store.
        workforce = LedgerWorkforce(ledger.employees)
        event_bus = EventBus()
        scheduler = Scheduler(
            tick_interval_s=the_caps.tick_interval_s,
            max_concurrent_runs=the_caps.max_concurrent_runs,
            ledger=ledger,
            workforce=workforce,
            beat_runner=beat_runner,
            beat_runner_for=beat_runner_for,  # role-faithful per-employee runners (spec 06 §2)
            event_bus=event_bus,
            # budgets are inert until a policy is created — injecting the enforcer just arms the gates
            budget_enforcer=BudgetEnforcer(ledger, company_id=company_id),
            roles=registry,  # a task inherits its assignee role's DoD at intake (spec 04 §1 / 06 §2)
        )
        return cls(
            ledger=ledger,
            workforce=workforce,
            memory_writer=AppendOnlyMemoryWriter(memory_repo),
            scheduler=scheduler,
            event_bus=event_bus,
            inspector=LedgerInspector(ledger),
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

    def request_hire(
        self,
        *,
        name: str,
        role: str,
        reports_to: str | None = None,
        budget_cents: int | None = None,
    ) -> HireRequest:
        """Hire an employee, gated by policy (spec 04 §5 ``hire_employee``).

        When ``governance_policy.hire_gate_required()``, the employee is created ``pending``
        (uninvokable) with its budget policy and a ``hire_employee`` approval is opened — a human
        approves (→ ``active``) or denies (→ ``terminated``). Otherwise the employee is hired directly,
        exactly as :meth:`hire` (the empty default policy reproduces today's behaviour)."""
        if role not in self._roles:
            raise OrgInvariantViolation(f"unknown role {role!r}")
        gated = self._governance_policy.hire_gate_required()
        status = EmployeeStatus.PENDING if gated else EmployeeStatus.IDLE
        employee = self._workforce.hire(
            name=name, role=role, reports_to=reports_to, status=status
        )
        if budget_cents is not None:
            self._create_employee_budget(employee.id, budget_cents)
        if not gated:
            return HireRequest(employee=employee, approval=None)
        approval = GovernanceResolver(self._ledger).open(
            action=ApprovalAction.HIRE_EMPLOYEE,
            subject_kind=ApprovalSubjectKind.EMPLOYEE,
            subject_id=employee.id,
            reason=f"hire {name} as {role}",
        )
        return HireRequest(employee=employee, approval=approval)

    def _create_employee_budget(self, employee_id: str, amount_cents: int) -> None:
        self._ledger.budget_policies.create(
            BudgetPolicy(
                id=f"bp_{uuid.uuid4().hex[:12]}",
                scope_type=BudgetScope.EMPLOYEE,
                scope_id=employee_id,
                amount=amount_cents,
            )
        )

    def terminate(self, employee_id: str) -> None:
        """Irreversibly terminate an employee; cancel its in-flight work (spec 06 §3).

        The terminate is the source of truth (irreversible, root-protected); cancelling the
        in-flight run and dropping queued wakes stops the scheduler dispatching the dead identity.
        """
        self._workforce.terminate(employee_id)
        self._ledger.runs.cancel_running(employee_id=employee_id)
        self._ledger.wakes.drop_queued(employee_id=employee_id)

    def register_role(self, plugin: RolePlugin, *, replace: bool = False) -> None:
        """Register a role plugin — fail-closed + idempotent (spec 09 §1)."""
        self._roles.register(plugin, replace=replace)

    # -- portability: org as data (spec 09 §3) --------------------------------

    def export_workforce(self, org_repo: str) -> int:
        """Serialize the live ledger org to a portable git-markdown tree (spec 09 §3).

        Writes ``<org_repo>/employees/<slug>/role.md`` for every non-terminated employee — the
        portable package is the *serialization* of the live store, not a second store. Returns the
        number of employees exported.
        """
        return copy_org(self._workforce, GitWorkforce(org_repo))

    def import_workforce(self, org_repo: str) -> int:
        """Materialize a git-markdown org into the live ledger store (spec 09 §3).

        Re-hires every employee under ``<org_repo>/employees/`` into the ledger (managers first, so
        each ``reports_to`` edge resolves as it lands). Returns the number imported.
        """
        return copy_org(GitWorkforce(org_repo), self._workforce)

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
