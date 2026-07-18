"""Budget-gate smoke — a real beat's token cost trips a hard-stop budget end to end (needs keys).

Not a test. Proves the spec 04 §3 loop with a real provider: a beat runs on Azure OpenAI, dream meters
its per-model tokens, chorus prices them into ``cost_cents``, the scheduler records a ``cost_event``,
and Gate 2 fires — the employee's tiny budget is blown, a hard incident opens, the scope is paused,
and the *next* dispatch is gated (Gate 1).

    AZURE_OPENAI_API_KEY=...
    AZURE_OPENAI_BASE_URL=https://<resource>.cognitiveservices.azure.com/openai/v1
    AZURE_OPENAI_DEPLOYMENT=<deployment>
    uv run python examples/budget_gate_smoke.py

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

from chorus.adapters import DreamBeatRunner, ModelRate, TokenPricing
from chorus.budgets import BudgetEnforcer
from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.ledger import BudgetPolicy, BudgetScope, Ledger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.workforce import Employee

_COMPANY = "acme"
_EMPLOYEE = "eng"
_INTENT = "Reply with the single word DONE."
# Illustrative GPT-5-class pricing (whole cents per million tokens); a `default` rate prices whatever
# model name dream reports, so the smoke never under-prices to zero.
_PRICING = TokenPricing(
    rates={}, default=ModelRate(input_cents_per_mtok=125, output_cents_per_mtok=1000)
)
_CAP_CENTS = 1  # a deliberately tiny cap so any real beat blows it


class _LedgerWorkforce:
    """The scheduler only needs ``get`` to rehydrate an employee — read it from the ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def get(self, employee_id: str) -> Employee:
        employee = self._ledger.employees.get(employee_id)
        if employee is None:
            raise KeyError(employee_id)
        return employee


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        print("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    now = datetime.now(UTC)
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
            enforcer = BudgetEnforcer(ledger, company_id=_COMPANY)
            scheduler = Scheduler(
                ledger=ledger,
                workforce=_LedgerWorkforce(ledger),
                beat_runner=DreamBeatRunner(harness, pricing=_PRICING),
                budget_enforcer=enforcer,
                max_concurrent_runs=1,
            )

            # Seed: an employee with a 1-cent monthly cap, and a task assigned to them.
            ledger.employees.create(Employee(id=_EMPLOYEE, name="alice", role="engineer"))
            ledger.budget_policies.create(
                BudgetPolicy(
                    id="bp1", scope_type=BudgetScope.EMPLOYEE, scope_id=_EMPLOYEE, amount=_CAP_CENTS
                )
            )
            ledger.tasks.submit(Task(id="t1", intent=_INTENT, status=TaskStatus.TODO))
            assign_task(ledger, "t1", _EMPLOYEE)

            async def _tick_and_drain() -> None:
                await scheduler.tick(now)
                await scheduler.drain()

            print("tick 1 — running a real beat; its token cost should blow the 1-cent cap…")
            asyncio.run(_tick_and_drain())

        # What did the beat cost, and did Gate 2 fire?
        spent = ledger.cost_events.spent_cents(_EMPLOYEE)
        incidents = ledger.budget_incidents.open_for_policy("bp1")
        blocked = enforcer.invocation_block(_EMPLOYEE, now=now)
        run = ledger.runs.for_task("t1")[-1]
        for ce in ledger.cost_events.for_run(run.id):
            print(
                f"  cost_event: model={ce.model!r} in={ce.input_tokens} out={ce.output_tokens} "
                f"cost={ce.cost_cents}c"
            )
        print(f"  spent: {spent} cents (cap {_CAP_CENTS})")
        print(f"  open incidents: {[i.threshold_type.value for i in incidents]}")
        print(f"  invocation_block now: {blocked.value if blocked is not None else None}")

        # Gate 1: the next assigned beat must not dispatch while the scope is paused.
        ledger.tasks.submit(Task(id="t2", intent=_INTENT, status=TaskStatus.TODO))
        ledger.wakes.enqueue(
            Wake(
                id="w2",
                employee_id=_EMPLOYEE,
                reason=WakeReason.TASK_ASSIGNED,
                payload={"task_id": "t2"},
            )
        )

        report2 = asyncio.run(scheduler.tick(now))
        print(
            f"tick 2 — budget_gated={report2.budget_gated}, beats_started={report2.beats_started}"
        )

        ok = spent > _CAP_CENTS and blocked is not None and report2.budget_gated == 1
        print("RESULT:", "PASS — real cost tripped the gate" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
