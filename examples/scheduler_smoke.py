"""Scheduler-driven smoke — a real task flows through run_forever end to end (manual; needs keys).

Not a test. Watches the kernel actually run the agent: an employee and a task go into the ledger,
``Scheduler.run()`` dispatches a real beat through ``DreamBeatRunner`` on Azure OpenAI, and the task
moves ``todo -> in_progress -> done`` on its own — no manual beat call.

    AZURE_OPENAI_API_KEY=...
    AZURE_OPENAI_BASE_URL=https://<resource>.cognitiveservices.azure.com/openai/v1
    AZURE_OPENAI_DEPLOYMENT=<deployment>
    uv run python examples/scheduler_smoke.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import dream  # type: ignore[import-not-found]

from chorus.adapters import DreamBeatRunner
from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.workforce import Employee

_EMPLOYEE = "eng"
_TASK = "t1"
_INTENT = "Reply with the single word DONE and mark the task complete."
_TERMINAL = (TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.BLOCKED)
_TIMEOUT_TICKS = 180  # ~3 min at the default 1s tick


class _LedgerWorkforce:
    """The Scheduler only needs ``get`` to rehydrate an employee — read it straight from the ledger.

    Inlined here for the smoke; a real Workforce (git-markdown, spec 06) or a promoted ledger-backed
    one is the productization step.
    """

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def get(self, employee_id: str) -> Employee:
        employee = self._ledger.employees.get(employee_id)
        if employee is None:
            raise KeyError(employee_id)
        return employee


async def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        print("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    ledger = SqliteLedger.open(":memory:")
    last_status = ""
    try:
        with tempfile.TemporaryDirectory() as work_dir:
            harness = dream.build_harness(
                model=deployment,
                api_key=api_key,
                base_url=base_url,
                working_dir=Path(work_dir),
                skills=False,
                memory=False,
                mcp=False,
                plugins=False,
            )
            scheduler = Scheduler(
                ledger=ledger,
                workforce=_LedgerWorkforce(ledger),
                beat_runner=DreamBeatRunner(harness),
                max_concurrent_runs=1,
            )

            # seed the work, then let the loop dispatch it
            ledger.employees.create(Employee(id=_EMPLOYEE, name="alice", role="engineer"))
            ledger.tasks.submit(Task(id=_TASK, intent=_INTENT))
            assign_task(ledger, _TASK, _EMPLOYEE)  # -> todo + the task_assigned wake the tick drains

            print(f"running the kernel — watching task {_TASK!r} flow through the loop")
            loop = asyncio.create_task(scheduler.run())
            try:
                for _ in range(_TIMEOUT_TICKS):
                    await asyncio.sleep(1)
                    task = ledger.tasks.get(_TASK)
                    assert task is not None
                    if task.status.value != last_status:
                        last_status = task.status.value
                        print(f"  task {_TASK}: {last_status}")
                    if task.status in _TERMINAL:
                        break
            finally:
                scheduler.stop()
                await loop

        # why did it land where it did? show the beat's verdict + the run record
        runs = ledger.runs.for_task(_TASK)
        if runs:
            run = runs[-1]
            print(f"run: status={run.status.value} liveness={run.liveness_state} "
                  f"outcome={run.outcome}")
        dod = ledger.dod.get_for_task(_TASK)
        if dod is not None:
            print(f"dod: status={dod.status.value} verdict={dod.verdict}")
    finally:
        ledger.close()

    print(f"final: {last_status}")
    return 0 if last_status == TaskStatus.DONE.value else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
