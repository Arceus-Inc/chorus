"""DoD smoke — the HumanApproval beat-hook and the self-repair ladder, end to end (spec 04 §1).

No keys, no dream, no network: a fake beat runner with a fixed verdict stands in for dream, so the
*chorus* logic is shown deterministically — a passing human-approval beat opens an approval (not
done); a failing Command beat re-wakes for self-repair, then escalates to a recovery_action once the
repair budget is spent.

    uv run python examples/dod_smoke.py
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from chorus.governance import ApprovalDecision, GovernanceResolver
from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.outcomes import Verifier
from chorus.workforce import Employee

_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


class _FixedBeat:
    """A stand-in dream beat with a fixed pass/fail verdict."""

    def __init__(self, *, passed: bool) -> None:
        self._passed = passed

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       rubric: object = "", observer: object = None, run_id: str | None = None) -> BeatOutcome:
        return BeatOutcome(passed=self._passed, outcome={}, summary="fake")


class _Workforce:
    def __init__(self, employee: Employee) -> None:
        self._employee = employee

    def get(self, employee_id: str) -> Employee:
        return self._employee


def _assign(ledger: SqliteLedger, task_id: str, verifier: Verifier) -> None:
    ledger.tasks.submit(
        Task(id=task_id, intent="do it", status=TaskStatus.TODO, assignee_employee_id="alice")
    )
    ledger.dod.create(task_id, verifier)
    ledger.wakes.enqueue(
        Wake(id=f"w_{task_id}", employee_id="alice", reason=WakeReason.TASK_ASSIGNED,
             payload={"task_id": task_id})
    )


async def _run_tick(scheduler: Scheduler) -> None:
    await scheduler.tick(_NOW)
    await scheduler.drain()


def main() -> int:
    ledger = SqliteLedger.open(":memory:")
    try:
        employee = ledger.employees.create(Employee(id="alice", name="Alice", role="engineer"))

        # 1) HumanApproval DoD: the beat passes, but a human must sign off → an approval opens.
        _assign(ledger, "spec", Verifier.human_approval())
        asyncio.run(_run_tick(Scheduler(
            ledger=ledger, workforce=_Workforce(employee),
            beat_runner=_FixedBeat(passed=True), max_concurrent_runs=1,
        )))
        gate = ledger.approvals.pending()[0]
        print(f"human-approval: beat ran → task 'spec' is "
              f"{ledger.tasks.get('spec').status.value}, approval {gate.id} opened")  # type: ignore[union-attr]
        GovernanceResolver(ledger).resolve(gate.id, decision=ApprovalDecision.APPROVE, decided_by_user_id="board", now=_NOW)
        print(f"  board approved → 'spec' is {ledger.tasks.get('spec').status.value}")  # type: ignore[union-attr]

        # 2) Command DoD that keeps failing: re-wake for self-repair, then escalate (budget = 1).
        _assign(ledger, "build", Verifier.command("false"))
        failing = Scheduler(
            ledger=ledger, workforce=_Workforce(employee),
            beat_runner=_FixedBeat(passed=False), max_concurrent_runs=1, max_repair_attempts=1,
        )
        asyncio.run(_run_tick(failing))  # 1st failure → re-wake (rung 1)
        retried = any(w.reason is WakeReason.RECOVERY for w in ledger.wakes.queued())
        print(f"command-fail #1: 'build' is {ledger.tasks.get('build').status.value}, "  # type: ignore[union-attr]
              f"self-repair re-wake queued = {retried}")
        asyncio.run(_run_tick(failing))  # retry fails → escalate (rung 3)
        recovery = ledger.recovery_actions.active_for_source("build")
        print(f"command-fail #2: repair budget spent → recovery_action "
              f"{recovery.id if recovery else None} opened, 'build' stays "
              f"{ledger.tasks.get('build').status.value}")  # type: ignore[union-attr]

        ok = (
            ledger.tasks.get("spec").status is TaskStatus.DONE  # type: ignore[union-attr]
            and retried
            and recovery is not None
        )
        print("RESULT:", "PASS — hook + ladder behaved" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
