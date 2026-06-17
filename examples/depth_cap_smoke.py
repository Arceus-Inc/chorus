"""Keys-free smoke: the delegation depth cap fails closed (spec 06 §4).

A manager fans a chain out hop by hop up to the cap; one more hop is **refused** — no child is
created, the over-cap task is set ``blocked``, and a typed ``recovery_action`` is opened naming the
manager. No provider or keys needed: the cap is deterministic chorus logic, so this runs anywhere.

    python examples/depth_cap_smoke.py
"""

from __future__ import annotations

from chorus.ledger import Artifact, ArtifactRevision, ArtifactType, SqliteLedger, Task
from chorus.ledger._models import TaskStatus
from chorus.lifecycle import ChildSpec, DepthCapped, Fanned, decompose
from chorus.workforce import Employee

_CAP = 2  # a small cap keeps the smoke short


def _accepted_plan(ledger: SqliteLedger, *, source_id: str, revision_id: str) -> str:
    """The manager's accepted plan revision the decomposition claim references (spec 02 §4)."""
    plan_id = f"plan_{source_id}"
    ledger.artifacts.create(Artifact(id=plan_id, task_id=source_id, type=ArtifactType.DOC))
    ledger.artifact_revisions.record(ArtifactRevision(id=revision_id, artifact_id=plan_id))
    return revision_id


def main() -> int:
    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="mgr", name="Boss", role="manager"))
        ledger.tasks.submit(Task(id="t0", intent="root goal", assignee_employee_id="mgr"))

        parent = "t0"
        for depth in range(1, _CAP + 1):  # fan out hops 1..cap — all allowed
            child_id = f"t{depth}"
            revision = _accepted_plan(ledger, source_id=parent, revision_id=f"rev_{depth}")
            outcome = decompose(
                ledger,
                source_task_id=parent,
                accepted_plan_revision_id=revision,
                children=[ChildSpec(Task(id=child_id, intent=f"hop {depth}", assignee_employee_id="mgr"))],
                request_depth_cap=_CAP,
            )
            assert isinstance(outcome, Fanned), f"hop {depth} should have fanned out"
            child = ledger.tasks.get(child_id)
            assert child is not None
            print(f"hop {depth}: decomposed {parent} -> {child_id} (request_depth={child.request_depth})")
            parent = child_id

        # one hop past the cap — must fail closed (no plan revision is needed: the cap is checked first)
        outcome = decompose(
            ledger,
            source_task_id=parent,
            accepted_plan_revision_id="rev_over",
            children=[ChildSpec(Task(id="over", intent="one hop too far", assignee_employee_id="mgr"))],
            request_depth_cap=_CAP,
        )
        assert isinstance(outcome, DepthCapped), "the over-cap decompose must fail closed"
        assert ledger.tasks.get("over") is None, "no child may be created at the cap"
        blocked = ledger.tasks.get(parent)
        assert blocked is not None and blocked.status is TaskStatus.BLOCKED
        recovery = outcome.recovery
        print(
            f"over cap: refused -- {parent} blocked; recovery {recovery.id} "
            f"cause={recovery.cause!r} owner={recovery.owner_employee_id}"
        )
        print("OK: delegation depth cap held")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
