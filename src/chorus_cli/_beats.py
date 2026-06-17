"""The console's composition root for running real beats — the one module that wires dream.

A :class:`BeatService` is a :class:`~chorus.heartbeat.Scheduler` wired with a real
:class:`~chorus.adapters.DreamBeatRunner`, plus the sync ``run_tick`` bridge the (synchronous)
console calls. :func:`build_beat_service` builds the dream harness from Azure credentials; it is the
only place in the CLI that imports dream, and it is imported lazily (only when keys are present), so
the keys-free console never pays for it.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import dream

from chorus.adapters import DreamBeatRunner, ModelRate, TokenPricing
from chorus.budgets import BudgetEnforcer
from chorus.heartbeat import Scheduler, TickReport
from chorus.ledger import SqliteLedger
from chorus.workforce import LedgerWorkforce
from chorus_cli._chat import ChatBeatService, ChatRenderBus
from chorus_cli._role_chat import build_role_chat_service

# Illustrative GPT-5-class pricing (whole cents per million tokens); override via env.
_DEFAULT_INPUT_CENTS_PER_MTOK = 125
_DEFAULT_OUTPUT_CENTS_PER_MTOK = 1000


def _env_int(name: str, default: int) -> int:
    """Read an integer env var, falling back to ``default`` when unset or malformed."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def default_pricing_from_env() -> TokenPricing:
    """A default-rate :class:`TokenPricing` so any model a beat reports accrues spend.

    Lives with the beat composition root (not the CLI entrypoint) so both the ``tick`` and ``chat``
    beat services price spend identically. Rates come from CHORUS_PRICE_INPUT/OUTPUT_CENTS_PER_MTOK.
    """
    return TokenPricing(
        rates={},
        default=ModelRate(
            _env_int("CHORUS_PRICE_INPUT_CENTS_PER_MTOK", _DEFAULT_INPUT_CENTS_PER_MTOK),
            _env_int("CHORUS_PRICE_OUTPUT_CENTS_PER_MTOK", _DEFAULT_OUTPUT_CENTS_PER_MTOK),
        ),
    )


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
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=DreamBeatRunner(harness, pricing=pricing),
        budget_enforcer=BudgetEnforcer(ledger, company_id=company_id),
        max_concurrent_runs=max_concurrent_runs,
    )
    return SchedulerTickRunner(scheduler, model=deployment)


def chat_service_from_env(
    ledger: SqliteLedger,
    *,
    employee_id: str,
    render_bus: ChatRenderBus,
    company_id: str,
) -> ChatBeatService | None:
    """Build a **role-aware** chat beat service from Azure creds, or ``None`` when unset (keys-free chat).

    The same three Azure variables gate a real beat (dream is imported only when present). The harness
    is materialized for the employee's role — its tools, memory, and a per-role overlay of its brief +
    permission posture — so the whole ``run_task`` loop runs as that employee (see
    :func:`chorus_cli._role_chat.build_role_chat_service`). ``CHORUS_COMPANY_SEED`` (a repo path/URL or
    a directory) seeds the company workspace on first creation so employees branch off real code.
    """
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        return None
    return build_role_chat_service(
        ledger,
        employee_id=employee_id,
        api_key=api_key,
        base_url=base_url,
        deployment=deployment,
        company_id=company_id,
        render_bus=render_bus,
        pricing=default_pricing_from_env(),
        seed=os.environ.get("CHORUS_COMPANY_SEED") or None,
    )


__all__ = [
    "SchedulerTickRunner",
    "build_beat_service",
    "chat_service_from_env",
    "default_pricing_from_env",
]
