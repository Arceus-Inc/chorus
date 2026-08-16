"""Governance smoke — open an approval gate, resolve it, watch the task move (spec 04 §5).

No keys, no dream, no network: pure ledger. Shows both gate kinds end to end —
an **acceptance** gate (approve → the task is *done*, its dependents unblock) and an
**authorization** gate (deny → the task is *cancelled*).

    uv run python examples/governance_smoke.py
"""

from __future__ import annotations

from chorus.ids import derive_id

_demo_salt = {"n": 0}  # bumped per ledger open — scenario reruns in one database can't collide


def _bump_demo_salt() -> None:
    _demo_salt["n"] += 1


def _id(name: str) -> str:
    """A readable per-scenario entity id (deterministic within a scenario, unique across them)."""
    return derive_id("demo", str(_demo_salt["n"]), name)


import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org

from datetime import UTC, datetime

from chorus.governance import (
    ApprovalDecision,
    GovernanceResolver,
    HumanAuthorization,
)
from chorus.ledger import ApprovalGate, AuthenticationMethod, Ledger, Task, TaskStatus
from chorus.workforce import Employee

_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
_USER = "operator"


def main() -> int:
    _bump_demo_salt()
    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=str(uuid.uuid4()),  # fresh org per open — slugs reset
    )
    try:
        resolver = GovernanceResolver(ledger)
        ledger.employees.create(Employee(id="alice", name="Alice", role="engineer"))

        # Acceptance gate: a human sign-off IS the task's done-ness; a dependent waits on it.
        ledger.tasks.submit(
            Task(
                id=_id("spec"),
                intent="write the spec",
                status=TaskStatus.IN_PROGRESS,
                assignee_employee_id="alice",
            )
        )
        ledger.tasks.submit(
            Task(id=_id("build"), intent="build from the spec", assignee_employee_id="alice")
        )
        ledger.dependencies.add(_id("build"), _id("spec"))  # build depends on spec

        gate = resolver.open_task_gate(
            _id("spec"), gate_kind=ApprovalGate.ACCEPTANCE, reason="board signs off the spec"
        )
        print(f"opened {gate.id} — 'spec' is now {ledger.tasks.get(_id('spec')).status.value}")  # type: ignore[union-attr]
        accept = resolver.resolve(
            gate.id, decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
        )
        print(
            f"approved → 'spec' is {accept.subject_status}; "
            f"{accept.wakes_fired} downstream wake(s) fired (build can start)"
        )

        # Authorization gate: sign-off BEFORE doing the work; denied → the task is cancelled.
        ledger.tasks.submit(
            Task(
                id=_id("risky"),
                intent="ship to prod on Friday",
                status=TaskStatus.IN_PROGRESS,
                assignee_employee_id="alice",
            )
        )
        gate2 = resolver.open_task_gate(
            _id("risky"), gate_kind=ApprovalGate.AUTHORIZATION, reason="authorise a Friday deploy"
        )
        deny = resolver.resolve_authenticated(
            gate2.id,
            decision=ApprovalDecision.DENY,
            authorization=HumanAuthorization(
                decision_id=_id("decision"),
                user_id=_USER,
                method=AuthenticationMethod.SESSION,
                authenticated_at=_NOW,
                nonce=_id("nonce"),
                decided_at=_NOW,
                request_id="governance-smoke",
                request_hash="sha256:governance-smoke",
            ),
        )
        print(f"denied  → 'risky' is {deny.subject_status}")

        ok = (
            ledger.tasks.get(_id("spec")).status is TaskStatus.DONE  # type: ignore[union-attr]
            and accept.wakes_fired == 1
            and ledger.tasks.get(_id("risky")).status is TaskStatus.CANCELLED  # type: ignore[union-attr]
        )
        print("RESULT:", "PASS — gates resolved into task outcomes" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
