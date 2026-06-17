"""Materialize an employee into a configured dream harness (spec 06 §2, spec 05).

A chorus employee *uses* a dream harness — the full ``run_task`` loop (planner → generator →
evaluator). Its identity (the resolved role, projected to a :class:`RoleBeatConfig`) configures that
**whole** harness:

- ``tools`` → the harness's tool registry (``build_harness(registry=…)``)
- ``skills`` / ``memory`` → ``build_harness`` flags + the per-employee working dir
- ``system_prompt`` (brief) + ``permission_mode`` → per-role overlays written to
  ``{working_dir}/roles/{planner,generator,evaluator}.toml``, which ``run_task`` reads (its
  ``harness_dir`` defaults to the harness working dir) — so all three intra-task roles run as the
  employee.

The beat is the unchanged :class:`DreamBeatRunner` over ``run_task``. dream is imported here (the
composition seam); chorus core stays dream-free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import dream
from dream.roles import default_role_manifest
from dream.tools._registry import ToolRegistry, ToolSource
from dream.tools.builtin import default_registry

from chorus.adapters import DreamBeatRunner, TokenPricing
from chorus.budgets import BudgetEnforcer
from chorus.errors import UnknownEmployee
from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger
from chorus.roles import RoleBeatConfig, RoleRegistry, default_roles, role_beat_config
from chorus.workforce import LedgerWorkforce
from chorus.workspace import CompanyWorkspace
from chorus_cli._chat import ChatBeatService, ChatRenderBus

# dream runs these three intra-task roles per task; the employee's identity is overlaid onto each.
_DREAM_ROLES: tuple[Literal["planner", "generator", "evaluator"], ...] = (
    "planner",
    "generator",
    "evaluator",
)

# chorus role tool names → dream built-in names. ``run_command`` is dream's ``bash``; chorus-only
# capability tools (submit_task / assign_task / query_data) have no built-in and are dropped.
_CHORUS_TO_DREAM_TOOL: dict[str, str] = {
    "read_file": "read_file",
    "write_file": "write_file",
    "run_command": "bash",
    "git": "git",
}


def dream_tool_names(chorus_tools: tuple[str, ...]) -> tuple[str, ...]:
    """Map a role's chorus tool allow-list to dream built-in names, dropping chorus-only tools."""
    return tuple(_CHORUS_TO_DREAM_TOOL[name] for name in chorus_tools if name in _CHORUS_TO_DREAM_TOOL)


def _role_registry(dream_names: tuple[str, ...]) -> ToolRegistry:
    """A dream registry holding only the role's built-in tools — the harness's effective toolset."""
    full = default_registry()
    registry = ToolRegistry()
    for name in dream_names:
        tool = full.get(name)
        if tool is not None:
            registry.register(tool, source=ToolSource.DEFAULT)
    return registry


def _toml_escape(value: str) -> str:
    """Escape a string into a single-line TOML basic string (the overlay values are short)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def write_role_overlays(harness_dir: Path, config: RoleBeatConfig) -> None:
    """Write planner/generator/evaluator overlays so the whole harness runs as the employee.

    Each overlay **appends** the employee's brief to that dream role's base prompt (keeping the role's
    orchestration instructions) and sets the employee's permission posture. ``run_task`` loads these
    from ``{harness_dir}/roles/{role}.toml``.
    """
    roles_dir = harness_dir / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    for role in _DREAM_ROLES:
        base = default_role_manifest(role).system_prompt
        prompt = f"{base}\n\n## Operating brief (your role in the org)\n{config.system_prompt}"
        overlay = (
            f'system_prompt = "{_toml_escape(prompt)}"\n'
            f'permission_mode = "{config.permission_mode}"\n'
        )
        (roles_dir / f"{role}.toml").write_text(overlay, encoding="utf-8")


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
    work_dir: Path | None = None,
    roles: RoleRegistry | None = None,
    seed: str | Path | None = None,
) -> ChatBeatService:
    """Wire a chat beat service whose harness runs AS the employee's role (spec 06 §2 → dream).

    Resolves ``employee_id``'s chorus role → a :class:`RoleBeatConfig`, materializes it into a
    configured dream harness (role tools, memory, + the role overlays that flavour the whole
    planner→generator→evaluator loop), and runs it through the standard :class:`DreamBeatRunner`.
    ``seed`` points the company workspace at a real repo/directory the first time it is created, so
    worktree-isolated employees branch off actual code instead of an empty tree.
    """
    employee = ledger.employees.get(employee_id)
    if employee is None:
        raise UnknownEmployee(f"no employee {employee_id!r}")
    registry = roles if roles is not None else RoleRegistry.from_plugins(default_roles())
    if employee.role not in registry:
        raise ValueError(f"role {employee.role!r} for {employee_id!r} is not a registered role")
    config = role_beat_config(registry.get(employee.role).manifest)

    # Where the employee works. An explicit ``work_dir`` is honoured as-is (tests / advanced callers).
    # Otherwise, a ``worktree`` role gets a branch-isolated worktree under the shared company root —
    # ``working_dir`` IS the worktree, because dream confines its tools to ``working_dir`` (so that is
    # what isolates one employee's edits from another's). Other isolation postures fall back to a flat
    # per-employee dir under the company root.
    company_root = Path.cwd() / ".chorus" / "chat" / company_id
    workspace: CompanyWorkspace | None = None
    if work_dir is not None:
        root = work_dir
    elif config.isolation == "worktree":
        workspace = CompanyWorkspace(company_root, seed=seed)
        root = workspace.worktree_for(employee_id).path
    else:
        root = company_root / employee_id
    root.mkdir(parents=True, exist_ok=True)
    write_role_overlays(root, config)  # the employee's identity overlays the whole harness

    # Every build_harness knob comes from the employee's config — this is where the employee *becomes*
    # its harness. config.model overrides the deployment when set (e.g. a cheaper/stronger per-role
    # model); an empty role env means "no override" (None), never an empty mapping.
    harness = dream.build_harness(
        model=config.model or deployment,
        api_key=api_key,
        base_url=base_url,
        working_dir=root,
        registry=_role_registry(dream_tool_names(config.tools)),
        # A role that declares skills enables dream's skill loading (from the working dir). dream
        # bundles no skills and chorus owns no skill *content* yet, so per-skill scoping (only the
        # role's named skills, à la tools) waits on chorus skill playbooks — a follow-up.
        skills=bool(config.skills),
        # Every role uses dream memory; chorus's memory_scope picks the *partition* (private/project/
        # team/company) — a concept dream's flat memory flag doesn't model yet, so scope is carried in
        # the config (and overlays) but not yet narrowed here. Follow-up: partition-scoped memory.
        memory=True,
        working_memory=config.working_memory,
        max_turns=config.max_turns,
        mcp=config.mcp,
        plugins=config.plugins,
        wake_model=config.wake_model,
        env=dict(config.env) or None,
    )
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=DreamBeatRunner(harness, pricing=pricing),
        budget_enforcer=BudgetEnforcer(ledger, company_id=company_id),
        event_bus=render_bus,
        max_concurrent_runs=1,
    )
    return ChatBeatService(
        scheduler,
        model=deployment,
        working_dir=str(root),
        harness_spec=config,
        workspace=workspace,
        employee_id=employee_id,
    )


__all__ = ["build_role_chat_service", "dream_tool_names", "write_role_overlays"]
