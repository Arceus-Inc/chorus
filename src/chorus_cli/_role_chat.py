"""Build a chat beat service over the org harness factory (spec 06 §2).

The conversational front door. It resolves the employee, materializes its role-faithful harness via the
shared :class:`~chorus_harness.EmployeeHarnessFactory`, and wraps one scheduler + the chat render bus
into a :class:`ChatBeatService`. The materialization itself (tools, per-role overlays, worktree, every
``build_harness`` scalar) lives in ``chorus_harness`` — chat and the kernel ``tick`` share it, so a
chat turn and an autonomous beat run the *same* employee in the *same* worktree (one identity).
"""

from __future__ import annotations

from pathlib import Path

from chorus.adapters import TokenPricing
from chorus.budgets import BudgetEnforcer
from chorus.errors import UnknownEmployee
from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger
from chorus.observability import EventBus, FanoutBus
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import LedgerWorkforce
from chorus_cli._chat import ChatBeatService, ChatRenderBus
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory


def build_role_chat_service(
    ledger: SqliteLedger,
    *,
    employee_id: str,
    api_key: str,
    base_url: str,
    deployment: str,
    company_id: str,
    render_bus: ChatRenderBus,
    pricing: TokenPricing | None = None,
    roles: RoleRegistry | None = None,
    seed: str | Path | None = None,
    work_root: Path | None = None,
    timeout_s: float | None = 90.0,
) -> ChatBeatService:
    """Wire a chat beat service whose harness runs AS the employee's role (spec 06 §2 → dream).

    Delegates the role → harness materialization to the org :class:`~chorus_harness.EmployeeHarnessFactory`
    (the same one the kernel ``tick`` uses), then runs it through one scheduler with the chat render bus.
    ``seed`` points the org workspace at a real repo the first time it is created; ``work_root`` overrides
    the ``.chorus/work`` base (tests / advanced callers).
    """
    employee = ledger.employees.get(employee_id)
    if employee is None:
        raise UnknownEmployee(f"no employee {employee_id!r}")
    registry = roles if roles is not None else RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=api_key,
        base_url=base_url,
        deployment=deployment,
        company_id=company_id,
        roles=registry,
        pricing=pricing,
        seed=seed,
        work_root=work_root,
        timeout_s=timeout_s,
    )
    materialized = factory.materialize(employee)  # role-faithful harness in the employee's worktree
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=materialized.runner,  # chat is one employee → one materialized runner
        budget_enforcer=BudgetEnforcer(ledger, company_id=company_id),
        event_bus=FanoutBus(render_bus, EventBus(log_path=factory.company_root / "events.jsonl")),
        roles=registry,  # a chat task inherits the employee role's DoD at intake (spec 04 §1)
        landers=default_landers(factory.company_root),  # a passed beat lands its role artifact (§2)
        max_concurrent_runs=1,
    )
    return ChatBeatService(
        scheduler,
        model=deployment,
        working_dir=str(materialized.working_dir),
        harness_spec=materialized.config,
        workspace=materialized.workspace,
        employee_id=employee_id,
    )


__all__ = ["build_role_chat_service"]
