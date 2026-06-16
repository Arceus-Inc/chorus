"""The console's composition root for running real beats — the one module that wires dream.

A :class:`BeatService` is a :class:`~chorus.heartbeat.Scheduler` wired with a real
:class:`~chorus.adapters.DreamBeatRunner`, plus the sync ``run_tick`` bridge the (synchronous)
console calls. :func:`build_beat_service` builds the dream harness from Azure credentials; it is the
only place in the CLI that imports dream, and it is imported lazily (only when keys are present), so
the keys-free console never pays for it.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import dream

from chorus.adapters import DreamBeatRunner, TokenPricing
from chorus.budgets import BudgetEnforcer
from chorus.heartbeat import Scheduler, TickReport
from chorus.ledger import SqliteLedger
from chorus.workforce import Employee


class LedgerWorkforce:
    """A :class:`~chorus.workforce.Workforce` backed by the ledger's employee rows.

    The scheduler only needs ``get`` to rehydrate an employee before a beat, and that is what the
    console drives. The mutating half of the protocol (``hire``/``terminate``/``list``) is not part
    of the tick path here — the console seeds the workforce by writing employee rows directly — so it
    stays unimplemented, mirroring the still-stubbed git-markdown ``GitWorkforce`` (spec 06).
    """

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def get(self, employee_id: str) -> Employee:
        employee = self._ledger.employees.get(employee_id)
        if employee is None:
            raise KeyError(employee_id)
        return employee

    def hire(self, *, name: str, role: str, reports_to: str | None = None) -> Employee:
        raise NotImplementedError("the console hires by writing employee rows, not via the scheduler")

    def terminate(self, employee_id: str) -> None:
        raise NotImplementedError("termination is not a tick-path operation in the console")

    def list(self) -> list[Employee]:
        raise NotImplementedError("the console has no workforce listing yet (spec 06)")


class SchedulerTickRunner:
    """A :class:`~chorus_cli._context.BeatService` over a wired scheduler.

    Bridges the synchronous console to the async kernel: each ``run_tick`` runs one ``tick_once`` and
    then ``drain``s the beats it dispatched, on a fresh event loop, so the call returns only once the
    beat has fully landed its verdict in the ledger.
    """

    def __init__(self, scheduler: Scheduler, *, model: str) -> None:
        self._scheduler = scheduler
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def run_tick(self) -> TickReport:
        return asyncio.run(self._tick_and_drain())

    async def _tick_and_drain(self) -> TickReport:
        report = await self._scheduler.tick_once()
        await self._scheduler.drain()
        return report


def build_beat_service(
    ledger: SqliteLedger,
    *,
    api_key: str,
    base_url: str,
    deployment: str,
    company_id: str,
    pricing: TokenPricing,
    work_dir: Path | None = None,
    max_concurrent_runs: int = 1,
) -> SchedulerTickRunner:
    """Wire a dream harness + scheduler into a :class:`SchedulerTickRunner` (the composition root).

    The beat runner is priced (``pricing``) so each beat accrues a real ``cost_cents``, and the
    scheduler carries a :class:`~chorus.budgets.BudgetEnforcer` for ``company_id`` — so a ``tick``
    records spend and the two budget gates actually fire. ``work_dir`` is dream's scratch directory; a
    throwaway temp dir is created when not given. The harness is lean (no skills/memory/mcp/plugins).
    """
    root = work_dir if work_dir is not None else Path(tempfile.mkdtemp(prefix="chorus-cli-"))
    harness = dream.build_harness(
        model=deployment,
        api_key=api_key,
        base_url=base_url,
        working_dir=root,
        skills=False,
        memory=False,
        mcp=False,
        plugins=False,
    )
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger),
        beat_runner=DreamBeatRunner(harness, pricing=pricing),
        budget_enforcer=BudgetEnforcer(ledger, company_id=company_id),
        max_concurrent_runs=max_concurrent_runs,
    )
    return SchedulerTickRunner(scheduler, model=deployment)


__all__ = [
    "LedgerWorkforce",
    "SchedulerTickRunner",
    "build_beat_service",
]
