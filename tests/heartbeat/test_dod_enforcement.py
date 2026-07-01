"""The beat enforces the task's DoD: run_beat hands the Command checks to the runner (spec 04 §1)."""

from __future__ import annotations

from datetime import datetime

import pytest

from chorus.governance import ApprovalDecision, GovernanceResolver
from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import ApprovalGate, SqliteLedger, Task, TaskStatus
from chorus.outcomes import VerificationStep, Verifier
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


class _RecordingBeat:
    """A beat runner with a fixed verdict that records the verification it was handed."""

    def __init__(self, *, passed: bool = True) -> None:
        self._passed = passed
        self.calls: list[str] = []
        self.verification: tuple[VerificationStep, ...] | None = None

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: tuple[VerificationStep, ...] = (),
        observer: object = None,
        rubric: object = "", run_id: str | None = None,
    ) -> BeatOutcome:
        self.calls.append(task_id)
        self.verification = verification
        return BeatOutcome(passed=self._passed, outcome={}, summary="ok")


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _seed(ledger: SqliteLedger) -> Employee:
    employee = ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    ledger.tasks.submit(
        Task(id="t1", intent="ship", status=TaskStatus.TODO, assignee_employee_id="e1")
    )
    ledger.wakes.enqueue(
        Wake(id="w1", employee_id="e1", reason=WakeReason.TASK_ASSIGNED, payload={"task_id": "t1"})
    )
    return employee


def _scheduler(
    ledger: SqliteLedger, beat: _RecordingBeat, employee: Employee, *, max_repair_attempts: int = 2
) -> Scheduler:
    return Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(employee),
        beat_runner=beat,
        max_concurrent_runs=1,
        max_repair_attempts=max_repair_attempts,
    )


async def _tick(ledger: SqliteLedger, beat: _RecordingBeat, employee: Employee) -> None:
    sched = _scheduler(ledger, beat, employee)
    await sched.tick(_NOW)
    await sched.drain()


async def test_run_beat_passes_the_command_dod_as_verification(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.command("pytest -q && ruff check ."))
    beat = _RecordingBeat()

    await _tick(ledger, beat, employee)

    assert beat.calls == ["t1"]
    assert beat.verification == (VerificationStep(command="pytest -q && ruff check ."),)


async def test_run_beat_with_no_dod_passes_no_verification(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)  # no DoD created
    beat = _RecordingBeat()

    await _tick(ledger, beat, employee)

    assert beat.verification == ()


# -- DoD at intake: a task inherits its assignee role's DoD when none is set (spec 04 §1 / 06 §2) ----


def _scheduler_with_roles(ledger: SqliteLedger, beat: _RecordingBeat, employee: Employee) -> Scheduler:
    from chorus.roles import RoleRegistry, default_roles

    return Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(employee),
        beat_runner=beat,
        roles=RoleRegistry.from_plugins(default_roles()),
        max_concurrent_runs=1,
    )


async def test_intake_applies_the_assignee_role_dod_when_none_set(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)  # an engineer with no explicit DoD
    beat = _RecordingBeat()
    sched = _scheduler_with_roles(ledger, beat, employee)

    await sched.tick(_NOW)
    await sched.drain()

    # the engineer's role DoD (a reviewed build) was inherited + persisted; it runs no objective step at
    # the engineer's OWN beat — the gate is a reviewer beat + a kernel-run command (M3 reviewed-build).
    from chorus.outcomes import DoDKind

    verifier = ledger.dod.verifier_for_task("t1")
    assert verifier is not None and verifier.kind is DoDKind.REVIEWED_BUILD
    assert beat.verification == ()


async def test_intake_does_not_override_an_explicit_dod(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.command("custom-check"))  # a human set the DoD already
    beat = _RecordingBeat()
    sched = _scheduler_with_roles(ledger, beat, employee)

    await sched.tick(_NOW)
    await sched.drain()

    assert beat.verification == (VerificationStep(command="custom-check"),)  # explicit wins


async def test_intake_without_a_roles_registry_leaves_the_task_dod_free(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)
    beat = _RecordingBeat()
    _scheduler(ledger, beat, employee)  # the plain scheduler carries no roles

    await _tick(ledger, beat, employee)

    assert beat.verification == ()  # no registry → no intake DoD (back-compat)


async def test_run_beat_with_a_human_approval_dod_passes_no_verification(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.human_approval())  # not an objective check
    beat = _RecordingBeat()

    await _tick(ledger, beat, employee)

    assert beat.verification == ()


# -- HumanApproval beat-hook (spec 04 §1 + §5) ------------------------------------------------------


async def test_human_approval_dod_opens_an_approval_instead_of_marking_done(
    ledger: SqliteLedger,
) -> None:
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.human_approval())

    await _tick(ledger, _RecordingBeat(passed=True), employee)

    task = ledger.tasks.get("t1")
    assert task is not None and task.status is TaskStatus.BLOCKED  # not done — pending a human
    pending = ledger.approvals.pending()
    assert len(pending) == 1 and pending[0].gate_kind is ApprovalGate.ACCEPTANCE
    # and a human signing off lands the task done
    GovernanceResolver(ledger).resolve(
        pending[0].id, decision=ApprovalDecision.APPROVE, decided_by_user_id="board", now=_NOW
    )
    assert ledger.tasks.get("t1").status is TaskStatus.DONE  # type: ignore[union-attr]


class _GatingBeat:
    """A beat that opens an authorization gate mid-run (as ``stage_go_live`` does), then passes."""

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    async def run_task(
        self, *, task_id: str, intent: str, verification: tuple[VerificationStep, ...] = (),
        observer: object = None, rubric: object = "", run_id: str | None = None,
    ) -> BeatOutcome:
        del intent, verification, observer, rubric, run_id
        GovernanceResolver(self._ledger).open_task_gate(
            task_id, gate_kind=ApprovalGate.AUTHORIZATION, reason="go-live publish"
        )
        return BeatOutcome(passed=True, outcome={}, summary="staged a go-live")


async def test_pending_gate_wins_over_the_dod_so_the_task_stays_blocked(ledger: SqliteLedger) -> None:
    # A tool (e.g. stage_go_live) opens a gate mid-beat → task BLOCKED. Even though the beat then
    # passes its Command DoD, the pending human gate must win: the task must NOT finalise `done`,
    # else resolving the gate (blocked → todo) becomes an illegal `done → todo`.
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.command("true"))  # a Command DoD that would pass

    await _tick(ledger, _GatingBeat(ledger), employee)

    task = ledger.tasks.get("t1")
    assert task is not None and task.status is TaskStatus.BLOCKED  # gate won over the DoD
    pending = ledger.approvals.pending()
    assert len(pending) == 1
    # and approving now completes cleanly (blocked → todo), not the crashing `done → todo`
    GovernanceResolver(ledger).resolve(
        pending[0].id, decision=ApprovalDecision.APPROVE, decided_by_user_id="board", now=_NOW
    )
    assert ledger.tasks.get("t1").status is TaskStatus.TODO  # type: ignore[union-attr]


async def test_command_dod_pass_marks_done_without_an_approval(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.command("pytest -q"))

    await _tick(ledger, _RecordingBeat(passed=True), employee)

    assert ledger.tasks.get("t1").status is TaskStatus.DONE  # type: ignore[union-attr]
    assert ledger.approvals.pending() == []


# -- self-repair ladder (spec 04 §1) ---------------------------------------------------------------


def _recovery_wakes(ledger: SqliteLedger) -> list[Wake]:
    return [w for w in ledger.wakes.queued() if w.reason is WakeReason.RECOVERY]


async def test_command_dod_failure_rewakes_for_self_repair(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.command("pytest -q"))

    await _tick(ledger, _RecordingBeat(passed=False), employee)  # 1st failure

    # rung 1: kept dispatchable (todo) with a re-wake — not yet "stuck"
    assert ledger.tasks.get("t1").status is TaskStatus.TODO  # type: ignore[union-attr]
    assert [w.payload.get("task_id") for w in _recovery_wakes(ledger)] == ["t1"]
    assert ledger.recovery_actions.active_for_source("t1") is None  # not escalated yet


async def test_command_dod_failure_escalates_when_repair_budget_is_spent(
    ledger: SqliteLedger,
) -> None:
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.command("pytest -q"))
    beat = _RecordingBeat(passed=False)
    sched = _scheduler(ledger, beat, employee, max_repair_attempts=1)

    await sched.tick(_NOW)  # tick 1: fail → 1 failed run ≤ 1 → re-wake
    await sched.drain()
    assert _recovery_wakes(ledger)  # a retry was queued

    await sched.tick(_NOW)  # tick 2: claims the retry → fail → 2 > 1 → escalate
    await sched.drain()
    assert ledger.recovery_actions.active_for_source("t1") is not None  # rung 3: recovery opened
    assert ledger.tasks.get("t1").status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert _recovery_wakes(ledger) == []  # no further retry — it waits for a human


async def test_failure_without_a_command_dod_just_blocks(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)  # no DoD

    await _tick(ledger, _RecordingBeat(passed=False), employee)

    assert ledger.tasks.get("t1").status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert _recovery_wakes(ledger) == []  # no DoD → no objective step to resume → block


async def test_non_command_dod_needs_changes_rewakes_to_continue(ledger: SqliteLedger) -> None:
    """A reviewed_build/agent_review ``needs-changes`` beat means the (multi-sprint) build isn't done —
    the kernel re-dispatches the assignee (bounded) to resume it, rather than stranding it ``blocked``
    where no later beat can finish it (spec 04 §1, spec 05 one-beat-one-sprint)."""
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.agent_review(reviewer_role="reviewer", rubric="correct"))

    await _tick(ledger, _RecordingBeat(passed=False), employee)  # needs-changes, not done yet

    assert ledger.tasks.get("t1").status is TaskStatus.TODO  # type: ignore[union-attr]
    assert [w.payload.get("task_id") for w in _recovery_wakes(ledger)] == ["t1"]  # re-dispatched
    assert ledger.recovery_actions.active_for_source("t1") is None  # not escalated yet


async def test_non_command_dod_escalates_when_repair_budget_is_spent(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.agent_review(reviewer_role="reviewer", rubric="correct"))
    beat = _RecordingBeat(passed=False)
    sched = _scheduler(ledger, beat, employee, max_repair_attempts=1)

    await sched.tick(_NOW)  # tick 1: needs-changes → 1 ≤ 1 → re-wake
    await sched.drain()
    assert _recovery_wakes(ledger)

    await sched.tick(_NOW)  # tick 2: claims retry → needs-changes → 2 > 1 → escalate
    await sched.drain()
    assert ledger.recovery_actions.active_for_source("t1") is not None
    assert ledger.tasks.get("t1").status is TaskStatus.BLOCKED  # type: ignore[union-attr]
