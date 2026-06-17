"""The org's role-faithful harness factory (spec 06 §2 → dream) — the one materializer.

Both the kernel ``tick`` and the conversational ``chat`` run a beat *as its employee*. This factory is
the single place that turns an employee into a configured dream harness: it resolves the employee's
role → :class:`~chorus.roles.RoleBeatConfig`, scopes the tool registry, writes the per-role overlays
(brief + permission posture onto each of dream's planner/generator/evaluator roles), and builds the
harness in the employee's **branch-isolated worktree** under ``.chorus/work/{org}/worktrees/{employee}``.

One factory per org (it owns the dream import and the org's creds/workspace). :meth:`runner_for` is the
:class:`~chorus.heartbeat.BeatRunnerFor` seam the scheduler dispatches through; :meth:`materialize`
additionally returns the worktree handle + resolved config the chat front-end surfaces (``/config`` /
``/merge``). Continuity is **path-based** — the worktree + memory live at a stable per-employee path —
so the factory rebuilds the harness per call without a cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import dream
from dream.roles import default_role_manifest
from dream.tools._registry import ToolRegistry, ToolSource
from dream.tools.builtin import default_registry

from chorus.adapters import DreamBeatRunner, TokenPricing
from chorus.heartbeat import BeatRunner
from chorus.roles import RoleBeatConfig, RoleRegistry, role_beat_config
from chorus.workforce import Employee
from chorus.workspace import CompanyWorkspace

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


@dataclass(frozen=True)
class EmployeeHarness:
    """The materialized result for one employee — its runner plus what a front-end surfaces."""

    runner: BeatRunner
    workspace: CompanyWorkspace | None  # the branch-isolated worktree handle (None when unisolated)
    working_dir: Path
    config: RoleBeatConfig


class EmployeeHarnessFactory:
    """Materialize a role-faithful, worktree-isolated dream harness per employee (one per org).

    Implements :class:`~chorus.heartbeat.BeatRunnerFor`, so a :class:`~chorus.heartbeat.Scheduler`
    dispatches every beat through ``runner_for(employee)`` and each runs as its employee.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        deployment: str,
        company_id: str,
        roles: RoleRegistry,
        pricing: TokenPricing | None = None,
        seed: str | Path | None = None,
        work_root: Path | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._deployment = deployment
        self._roles = roles
        self._pricing = pricing
        self._seed = seed
        # The org's workspace root: .chorus/work/{org}/ — shared by chat and tick (one identity).
        base = work_root if work_root is not None else Path.cwd() / ".chorus" / "work"
        self._company_root = base / company_id

    @property
    def company_root(self) -> Path:
        """The org's workspace root (``.chorus/work/{org}/``) — where landers find the worktrees."""
        return self._company_root

    def runner_for(self, employee: Employee) -> BeatRunner:
        """The :class:`~chorus.heartbeat.BeatRunnerFor` seam — the role-faithful runner for a beat."""
        return self.materialize(employee).runner

    def materialize(self, employee: Employee) -> EmployeeHarness:
        """Resolve ``employee``'s role into a configured dream harness in its isolated worktree."""
        if employee.role not in self._roles:
            raise ValueError(f"role {employee.role!r} for {employee.id!r} is not a registered role")
        config = role_beat_config(self._roles.get(employee.role).manifest)

        # ``working_dir`` IS the worktree, because dream confines its tools to it — that is what
        # isolates one employee's edits from another's. A non-worktree posture falls back to a flat
        # per-employee dir under the org root.
        workspace: CompanyWorkspace | None = None
        if config.isolation == "worktree":
            workspace = CompanyWorkspace(self._company_root, seed=self._seed)
            root = workspace.worktree_for(employee.id).path
        else:
            root = self._company_root / employee.id
        root.mkdir(parents=True, exist_ok=True)
        write_role_overlays(root, config)  # the employee's identity overlays the whole harness

        # Every build_harness knob comes from the role config — this is where the employee *becomes*
        # its harness. config.model overrides the deployment when set; an empty role env means None.
        harness = dream.build_harness(
            model=config.model or self._deployment,
            api_key=self._api_key,
            base_url=self._base_url,
            working_dir=root,
            registry=_role_registry(dream_tool_names(config.tools)),
            skills=bool(config.skills),
            memory=True,
            working_memory=config.working_memory,
            max_turns=config.max_turns,
            mcp=config.mcp,
            plugins=config.plugins,
            wake_model=config.wake_model,
            env=dict(config.env) or None,
        )
        return EmployeeHarness(
            runner=DreamBeatRunner(harness, pricing=self._pricing),
            workspace=workspace,
            working_dir=root,
            config=config,
        )


__all__ = [
    "EmployeeHarness",
    "EmployeeHarnessFactory",
    "dream_tool_names",
    "write_role_overlays",
]
