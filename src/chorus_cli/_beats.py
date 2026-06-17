"""The console's composition root for running real beats (spec 06 §2, spec 10 §1).

A :class:`BeatService` is a :class:`~chorus.heartbeat.Scheduler` wired with the org's
:class:`~chorus_harness.EmployeeHarnessFactory`, plus the sync ``run_tick`` bridge the (synchronous)
console calls. ``tick`` and ``chat`` run beats through the *same* factory, so every dispatched beat
runs as its employee — role tools, brief, permission posture, and its own branch-isolated worktree.
The dream import lives in ``chorus_harness`` (imported lazily, only when keys are present), so the
keys-free console never pays for it.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from chorus.adapters import ModelRate, TokenPricing
from chorus.budgets import BudgetEnforcer
from chorus.heartbeat import Scheduler, TickReport
from chorus.ledger import SqliteLedger
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import LedgerWorkforce
from chorus_cli._chat import ChatBeatService, ChatRenderBus
from chorus_cli._role_chat import build_role_chat_service
from chorus_harness import EmployeeHarnessFactory

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
    seed: str | Path | None = None,
    work_root: Path | None = None,
    max_concurrent_runs: int = 1,
) -> SchedulerTickRunner:
    """Wire the org harness factory + scheduler into a :class:`SchedulerTickRunner` (spec 06 §2).

    Every dispatched beat is resolved through the :class:`~chorus_harness.EmployeeHarnessFactory`, so it
    runs as its employee — role tools/brief/permission/memory in the employee's own worktree under
    ``.chorus/work/{org}/`` (``work_root`` overrides the base; ``seed`` points it at a real repo). The
    factory is priced so each beat accrues ``cost_cents`` and the scheduler's
    :class:`~chorus.budgets.BudgetEnforcer` gates fire; ``roles`` also drives DoD-at-intake.
    """
    registry = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=api_key,
        base_url=base_url,
        deployment=deployment,
        company_id=company_id,
        roles=registry,
        pricing=pricing,
        seed=seed,
        work_root=work_root,
    )
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner_for=factory,  # resolve a role-faithful runner per dispatched employee
        budget_enforcer=BudgetEnforcer(ledger, company_id=company_id),
        roles=registry,  # tasks inherit the assignee role's DoD at intake (spec 04 §1)
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
