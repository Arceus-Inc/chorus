"""DoD LLM smoke — a real beat triggers the HumanApproval hook (spec 04 §1 + §5).

Runs one real beat on Azure OpenAI for a task whose DoD is a ``HumanApproval``: when dream's plan
completes, chorus opens an **approval** instead of finishing the task, which a human then approves to
land it *done*. (The objective Command-gate enforcement and the self-repair ladder are shown
deterministically in ``examples/dod_smoke.py``; a real failing command makes dream loop its sprints.)

    AZURE_OPENAI_API_KEY=...
    AZURE_OPENAI_BASE_URL=https://<resource>.cognitiveservices.azure.com/openai/v1
    AZURE_OPENAI_DEPLOYMENT=<deployment>
    uv run python examples/dod_llm_smoke.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import asyncio
import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import dream  # type: ignore[import-not-found]

from chorus.adapters import DreamBeatRunner
from chorus.governance import ApprovalDecision, GovernanceResolver
from chorus.heartbeat import Scheduler
from chorus.ledger import Ledger, Task
from chorus.lifecycle import assign_task
from chorus.outcomes import Verifier
from chorus.workforce import Employee

_NOW = datetime.now(UTC)
_INTENT = "Reply with the single word DONE."


class _LedgerWorkforce:
    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def get(self, employee_id: str) -> Employee:
        employee = self._ledger.employees.get(employee_id)
        if employee is None:
            raise KeyError(employee_id)
        return employee


async def _tick(scheduler: Scheduler) -> None:
    await scheduler.tick(_NOW)
    await scheduler.drain()


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        print("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
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
            ledger.employees.create(Employee(id="eng", name="alice", role="engineer"))

            # HumanApproval DoD — a completed plan opens an approval, not done.
            ledger.tasks.submit(Task(id="sign", intent=_INTENT))
            ledger.dod.create("sign", Verifier.human_approval())
            assign_task(ledger, "sign", "eng")
            print("tick — HumanApproval DoD, real beat…")
            asyncio.run(_tick(scheduler))
            pending = ledger.approvals.pending()
            sign_status = ledger.tasks.get("sign").status.value  # type: ignore[union-attr]
            if pending:
                print(f"  beat ran → 'sign' is {sign_status}, approval {pending[0].id} opened")
                GovernanceResolver(ledger).resolve(
                    pending[0].id,
                    decision=ApprovalDecision.APPROVE,
                    decided_by_user_id="board",
                    now=_NOW,
                )
                print(f"  board approved → 'sign' is {ledger.tasks.get('sign').status.value}")  # type: ignore[union-attr]
            else:
                print(f"  beat did not complete the plan → 'sign' is {sign_status} (no approval)")

        print("done — see the statuses above")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
