"""Per-beat memory capture: every beat lands one provenance-stamped episodic delta (spec 07 §3).

After a beat, the scheduler writes exactly one ``sprint_delta`` through the injected ``MemoryWriter`` —
honest fields derived from the run (the disposition's outcome, the employee's scope, the run id as
provenance), never authored by the worker. A cancelled beat (nothing happened) writes nothing. With no
writer injected the kernel is unchanged (writer-agnostic).
"""

from __future__ import annotations

import pytest
from dream.contracts import MemoryDelta, MemoryRecord, MemoryScope, MemoryType

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration


class _RecordingWriter:
    """A fake ``MemoryWriter`` that records the deltas applied to it."""

    def __init__(self) -> None:
        self.applied: list[MemoryDelta] = []

    async def apply(self, delta: MemoryDelta) -> MemoryRecord:
        self.applied.append(delta)
        return MemoryRecord(
            id=delta.target_id, scope=delta.scope, type=MemoryType.PROJECT,
            content=delta.new_content or "",
        )

    async def rollback(self, record_id: str, to_version: str) -> MemoryRecord:  # pragma: no cover
        raise NotImplementedError


class _Beat:
    """A :class:`BeatRunner` with a fixed disposition + a human-readable summary."""

    def __init__(self, *, disposition: BeatDisposition = BeatDisposition.PASSED) -> None:
        self._disposition = disposition

    async def run_task(
        self, *, task_id: str, intent: str, verification: object = (), observer: object = None, run_id: str | None = None
    ) -> BeatOutcome:
        passed = self._disposition is BeatDisposition.PASSED
        return BeatOutcome(
            passed=passed, disposition=self._disposition,
            outcome={"score": 0.91} if passed else {"error": "boom"},
            summary="added subtract(); tests pass",
        )


def _dispatch(ledger: SqliteLedger, beat: _Beat, writer: _RecordingWriter | None) -> Scheduler:
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="add subtract", status=TaskStatus.TODO, assignee_employee_id="ada"))
    ledger.dod.create("t1", Verifier.command("true"))  # objective DoD: land directly, not via review
    ledger.wakes.enqueue(Wake(id="w1", employee_id="ada", reason=WakeReason.MANUAL, payload={"task_id": "t1"}))
    return Scheduler(
        ledger=ledger, workforce=LedgerWorkforce(ledger.employees), beat_runner=beat,
        roles=RoleRegistry.from_plugins(default_roles()), memory_writer=writer,
        max_concurrent_runs=1,
    )


async def test_a_passed_beat_captures_one_provenance_stamped_delta(ledger: SqliteLedger) -> None:
    writer = _RecordingWriter()
    sched = _dispatch(ledger, _Beat(), writer)
    await sched.tick_once()
    await sched.drain()

    assert len(writer.applied) == 1
    delta = writer.applied[0]
    run_id = ledger.runs.for_task("t1")[-1].id
    assert delta.target_id == run_id  # provenance: the record is named by the run that produced it
    assert delta.scope is MemoryScope.PROJECT  # the engineer's memory scope
    md = delta.metadata
    assert md["task_id"] == "t1" and md["employee_id"] == "ada"
    assert md["outcome"] == "done"  # disposition mirror
    assert "subtract" in (delta.new_content or "")  # the beat's summary is the body


async def test_a_failed_beat_is_still_captured(ledger: SqliteLedger) -> None:
    writer = _RecordingWriter()
    sched = _dispatch(ledger, _Beat(disposition=BeatDisposition.DOD_FAILED), writer)
    await sched.tick_once()
    await sched.drain()
    assert len(writer.applied) == 1
    assert writer.applied[0].metadata["outcome"] == "needs_changes"


async def test_no_writer_is_a_noop(ledger: SqliteLedger) -> None:
    sched = _dispatch(ledger, _Beat(), writer=None)  # kernel stays writer-agnostic
    await sched.tick_once()
    await sched.drain()
    assert ledger.tasks.get("t1").status is TaskStatus.DONE  # type: ignore[union-attr]
