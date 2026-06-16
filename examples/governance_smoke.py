"""Governance smoke — open an approval gate, resolve it, watch the task move (spec 04 §5).

No keys, no dream, no network: pure ledger. Shows both gate kinds end to end —
an **acceptance** gate (approve → the task is *done*, its dependents unblock) and an
**authorization** gate (deny → the task is *cancelled*).

    uv run python examples/governance_smoke.py
"""

from __future__ import annotations

from datetime import UTC, datetime

from chorus.governance import GovernanceResolver
from chorus.ledger import ApprovalGate, SqliteLedger, Task, TaskStatus
from chorus.workforce import Employee

_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
_USER = "operator"


def main() -> int:
    ledger = SqliteLedger.open(":memory:")
    try:
        resolver = GovernanceResolver(ledger)
        ledger.employees.create(Employee(id="alice", name="Alice", role="engineer"))

        # Acceptance gate: a human sign-off IS the task's done-ness; a dependent waits on it.
        ledger.tasks.submit(Task(id="spec", intent="write the spec",
                                 status=TaskStatus.IN_PROGRESS, assignee_employee_id="alice"))
        ledger.tasks.submit(Task(id="build", intent="build from the spec",
                                 assignee_employee_id="alice"))
        ledger.dependencies.add("build", "spec")  # build depends on spec

        gate = resolver.open_task_gate("spec", gate_kind=ApprovalGate.ACCEPTANCE,
                                       reason="board signs off the spec")
        print(f"opened {gate.id} — 'spec' is now {ledger.tasks.get('spec').status.value}")  # type: ignore[union-attr]
        accept = resolver.resolve(gate.id, approve=True, decided_by_user_id=_USER, now=_NOW)
        print(f"approved → 'spec' is {accept.task_status.value}; "
              f"{accept.wakes_fired} downstream wake(s) fired (build can start)")

        # Authorization gate: sign-off BEFORE doing the work; denied → the task is cancelled.
        ledger.tasks.submit(Task(id="risky", intent="ship to prod on Friday",
                                 status=TaskStatus.IN_PROGRESS, assignee_employee_id="alice"))
        gate2 = resolver.open_task_gate("risky", gate_kind=ApprovalGate.AUTHORIZATION,
                                        reason="authorise a Friday deploy")
        deny = resolver.resolve(gate2.id, approve=False, decided_by_user_id=_USER, now=_NOW)
        print(f"denied  → 'risky' is {deny.task_status.value}")

        ok = (
            ledger.tasks.get("spec").status is TaskStatus.DONE  # type: ignore[union-attr]
            and accept.wakes_fired == 1
            and ledger.tasks.get("risky").status is TaskStatus.CANCELLED  # type: ignore[union-attr]
        )
        print("RESULT:", "PASS — gates resolved into task outcomes" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
