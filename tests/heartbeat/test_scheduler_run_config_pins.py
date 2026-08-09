"""The scheduler leaves runs unpinned until it can publish their exact configuration."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from chorus.events import Event
from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import (
    Ledger,
    Task,
)
from chorus.outcomes import VerificationStep
from chorus.testing import uid
from chorus.workforce import Employee, LedgerWorkforce

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _TaskPayload(Mapping[str, str]):
    task_id: str

    def __getitem__(self, key: str) -> str:
        if key != "task_id":
            raise KeyError(key)
        return self.task_id

    def __iter__(self) -> Iterator[str]:
        yield "task_id"

    def __len__(self) -> int:
        return 1


class _PassedBeat:
    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: tuple[VerificationStep, ...] = (),
        rubric: str = "",
        observer: Callable[[Event], None] | None = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        return BeatOutcome(passed=True)


async def test_scheduler_dispatches_fresh_employee_without_a_config_revision(ledger: Ledger) -> None:
    employee = ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    task = ledger.tasks.submit(Task(id=uid("pinned-heartbeat-task"), intent="ship it"))
    ledger.wakes.enqueue(
        Wake(
            id=uid("pinned-heartbeat-wake"),
            employee_id=employee.id,
            reason=WakeReason.TASK_ASSIGNED,
            payload=_TaskPayload(task.id),
        )
    )
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=_PassedBeat(),
    )

    await scheduler.tick(_NOW)
    await scheduler.drain()

    (run,) = ledger.runs.for_task(task.id)
    assert run.agent_config_revision is None
