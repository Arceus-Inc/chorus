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
from datetime import UTC, datetime
from typing import Any

from chorus.budgets import BudgetEnforcer
from chorus.cron import parse_cron
from chorus.errors import OrgInvariantViolation
from chorus.governance import GovernancePolicy, GovernanceResolver
from chorus.groups import InspectFacade
from chorus.heartbeat import BeatRunner, BeatRunnerFor, Scheduler, TickReport, Wake
from chorus.ledger import (
    Approval,
    ApprovalAction,
    ApprovalSubjectKind,
    BudgetPolicy,
    BudgetScope,
    Message,
    Routine,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineStatus,
    RoutineTarget,
    RoutineTrigger,
    SqliteLedger,
    Task,
    TaskPriority,
    TriggerKind,
)
from chorus.lifecycle import (
    DEFAULT_REQUEST_DEPTH_CAP,
    ReviseOutcome,
    assign_task,
    deliver_message,
    revise_dod,
)
from chorus.memory import AppendOnlyMemoryWriter
from chorus.observability import EventBus, LedgerInspector, RoutineView, WorkforceStatus
from chorus.outcomes import Verifier
from chorus.roles import RolePlugin, RoleRegistry, default_roles
from chorus.workforce import (
    Employee,
    EmployeeStatus,
    GitWorkforce,
    LedgerWorkforce,
    Workforce,
    copy_org,
    slugify,
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
        # Low-level grouped surfaces (spec 14 §2.2) — built once over the same backends.
        self._inspect = InspectFacade(inspector, event_bus)

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
        priority: TaskPriority = TaskPriority.MEDIUM,
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
            Task(id=f"task_{uuid.uuid4().hex[:12]}", intent=intent, priority=priority)
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

    def revise_dod(
        self, task_id: str, new_verifier: Verifier, *, revised_by: str
    ) -> ReviseOutcome:
        """Revise a task's DoD (spec 04 §1): a manager tighten applies now; a loosen opens a §5 gate.

        Raises ``RevisionAuthorityError`` if ``revised_by`` is not the assignee's manager, or
        ``NoRevision`` if the task has no DoD / the edit is a no-op."""
        return revise_dod(
            self._ledger, task_id=task_id, new_verifier=new_verifier, revised_by=revised_by
        )

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

    def request_promotion(self, artifact_id: str) -> Approval | None:
        """Promote a landed artifact to the board, gated by policy (spec 04 §5 ``board_approval``).

        When ``governance_policy.board_gate_required(<artifact class>)``, opens a ``board_approval``
        gate on the artifact (a human approves the promotion); otherwise returns ``None`` (promotion is
        ungated). Raises ``OrgInvariantViolation`` if the artifact is unknown."""
        artifact = self._ledger.artifacts.get(artifact_id)
        if artifact is None:
            raise OrgInvariantViolation(f"no such artifact {artifact_id!r}")
        if not self._governance_policy.board_gate_required(artifact.type.value):
            return None
        return GovernanceResolver(self._ledger).open(
            action=ApprovalAction.BOARD_APPROVAL,
            subject_kind=ApprovalSubjectKind.ARTIFACT,
            subject_id=artifact_id,
            reason=f"promote {artifact.type.value} to the board",
        )

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
        target: RoutineTarget = RoutineTarget.SPAWN_TASK,
        concurrency: RoutineConcurrency = RoutineConcurrency.COALESCE,
        catch_up: RoutineCatchUp = RoutineCatchUp.SKIP_MISSED,
        timezone: str = "UTC",
    ) -> RoutineView:
        """Create a cron routine owned by ``employee`` and its due trigger (spec 13 §3.1).

        ``employee`` is resolved by slug (fail-closed: an unknown employee raises ``UnknownEmployee``
        before anything is written). The firing engine already exists — this is the reachability seam
        that lets a routine be *created*; the tick's CRON step picks it up from ``next_run_at``.
        """
        employee_id = self._workforce.get(slugify(employee)).id  # fail-closed on unknown
        # Resolve the first edge *before* any write so a bad cron leaves no orphan routine.
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

    def list_routines(self, *, employee: str | None = None) -> list[RoutineView]:
        """Every routine, optionally scoped to one employee (resolved by slug) (spec 13 §7)."""
        employee_id = None if employee is None else self._workforce.get(slugify(employee)).id
        return self._inspector.list_routines(employee_id=employee_id)

    def routine(self, routine_id: str) -> RoutineView:
        """One routine resolved for reading — definition + triggers + recent firings (spec 13 §7)."""
        return self._inspector.routine(routine_id)

    def pause_routine(self, routine_id: str) -> None:
        """Stop a routine from firing (a paused routine drops out of the tick's CRON scan) (spec 13 §3.2)."""
        self._ledger.routines.set_status(routine_id, RoutineStatus.PAUSED)

    def resume_routine(self, routine_id: str) -> None:
        """Resume a paused routine — its trigger's ``next_run_at`` starts selecting again (spec 13 §3.2)."""
        self._ledger.routines.set_status(routine_id, RoutineStatus.ACTIVE)

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
