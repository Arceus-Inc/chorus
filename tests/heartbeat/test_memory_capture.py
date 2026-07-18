"""Per-beat memory capture: every beat lands one provenance-stamped episodic record (spec 07 §3).

After a beat, the scheduler appends exactly one ``SprintDelta`` to the injected ``EpisodicStore`` —
honest fields derived from the run (the disposition's outcome, the employee's scope, the run id as
provenance), never authored by the worker. A cancelled beat (nothing happened) writes nothing. With no
store injected the kernel is unchanged (writer-agnostic).
"""

from __future__ import annotations

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.memory import SprintDelta
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration


class _RecordingStore:
    """A fake ``EpisodicStore`` that records the deltas appended to it."""

    def __init__(self) -> None:
        self.appended: list[SprintDelta] = []

    def append(self, delta: SprintDelta) -> None:
        self.appended.append(delta)


class _Beat:
    """A :class:`BeatRunner` with a fixed disposition + a human-readable summary."""

    def __init__(self, *, disposition: BeatDisposition = BeatDisposition.PASSED) -> None:
        self._disposition = disposition

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        passed = self._disposition is BeatDisposition.PASSED
        return BeatOutcome(
            passed=passed,
            disposition=self._disposition,
            outcome={"score": 0.91} if passed else {"error": "boom"},
            summary="added subtract(); tests pass",
        )


def _dispatch(ledger: Ledger, beat: _Beat, store: _RecordingStore | None) -> Scheduler:
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.tasks.submit(
        Task(
            id=uid("t1"), intent="add subtract", status=TaskStatus.TODO, assignee_employee_id="ada"
        )
    )
    ledger.dod.create(
        uid("t1"), Verifier.command("true")
    )  # objective DoD: land directly, not via review
    ledger.wakes.enqueue(
        Wake(
            id=uid("w1"),
            employee_id="ada",
            reason=WakeReason.MANUAL,
            payload={"task_id": uid("t1")},
        )
    )
    return Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=beat,
        roles=RoleRegistry.from_plugins(default_roles()),
        memory_writer=store,
        max_concurrent_runs=1,
    )


async def test_a_passed_beat_captures_one_provenance_stamped_delta(ledger: Ledger) -> None:
    store = _RecordingStore()
    sched = _dispatch(ledger, _Beat(), store)
    await sched.tick_once()
    await sched.drain()

    assert len(store.appended) == 1
    delta = store.appended[0]
    run_id = ledger.runs.for_task(uid("t1"))[-1].id
    assert delta.run_id == run_id  # provenance: the record is named by the run that produced it
    assert delta.scope == "project"  # the engineer's memory scope
    assert delta.task_id == uid("t1") and delta.employee_id == "ada"
    assert delta.outcome == "done"  # disposition mirror
    assert "subtract" in delta.body  # the beat's summary is the body


async def test_a_failed_beat_is_still_captured(ledger: Ledger) -> None:
    store = _RecordingStore()
    sched = _dispatch(ledger, _Beat(disposition=BeatDisposition.DOD_FAILED), store)
    await sched.tick_once()
    await sched.drain()
    assert len(store.appended) == 1
    assert store.appended[0].outcome == "needs_changes"


async def test_no_store_is_a_noop(ledger: Ledger) -> None:
    sched = _dispatch(ledger, _Beat(), store=None)  # kernel stays writer-agnostic
    await sched.tick_once()
    await sched.drain()
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.DONE  # type: ignore[union-attr]
