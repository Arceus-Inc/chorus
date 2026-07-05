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

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import dream
from dream.roles import default_role_manifest
from dream.skills import load_skill_registry
from dream.subagents import Subagent, SubagentSet
from dream.subagents._projection import build_subagent_set
from dream.tools._base import BaseTool
from dream.tools._registry import ToolRegistry, ToolSource
from dream.tools.builtin import default_registry

from chorus.adapters import DreamBeatRunner, TokenPricing
from chorus.heartbeat import BeatRunner, IntegrateContextPacket
from chorus.outcomes import LanderRegistry, runtime_brief_block
from chorus.roles import RoleBeatConfig, RoleRegistry, role_beat_config
from chorus.roles._manifest import McpServerSpec
from chorus.roles._subagent import SubagentSpec
from chorus.trust import TrustPolicy
from chorus.workforce import Employee
from chorus.workspace import CompanyWorkspace, default_work_root
from chorus_employee import default_landers
from chorus_harness._trust import apply_trust
from chorus_tools import (
    AssignTaskTool,
    BrandLintTool,
    DecomposeTool,
    DesignExemplarTool,
    DesignLintTool,
    GoLiveTool,
    SubmitTaskTool,
    SubmitVerdictTool,
    TestEvidenceTool,
    analysis_tool,
)
from chorus_tools.cms import CmsDraftTool, cms_backend_from_env
from chorus_tools.delivery import (
    ExecuteGoLiveTool,
    email_delivery_from_env,
    publish_backend_from_env,
)

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger

# dream runs these three intra-task roles per task; the employee's identity is overlaid onto each.
_DREAM_ROLES: tuple[Literal["planner", "generator", "evaluator"], ...] = (
    "planner",
    "generator",
    "evaluator",
)

# chorus role tool names → dream built-in names. ``run_command`` is dream's ``bash``. chorus-only
# capability tools (decompose / submit_task / assign_task / query_data) have no built-in: M3 tools are
# registered from ``chorus_tools`` because they need the ledger — see ``_capability_tool``.
_CHORUS_TO_DREAM_TOOL: dict[str, str] = {
    "read_file": "read_file",
    "write_file": "write_file",
    "run_command": "bash",
    "git": "git",
    "skill": "skill",
    "memory_search": "memory_search",
    "memory_get": "memory_get",
    "working_memory_read": "working_memory_read",
    "working_memory_write": "working_memory_write",
    "working_memory_append": "working_memory_append",
    "memory_propose": "memory_propose",
    "spawn_subagent": "spawn_subagent",
    # Web research: reuse dream's native Tavily built-ins (in default_registry) — identity-mapped so
    # dream_tool_names keeps them and _role_registry picks them up; the subagent projection carries them.
    "web_search": "web_search",
    "web_extract": "web_extract",
    # Reading spilled tool output: a large tool result (a web_extract page, a repo_search dump) is
    # offloaded to the session scratch dir with a "Full output saved to: <file>" pointer — read_offloaded
    # (tier-0, scratch-confined) is how a role pulls that full payload back. Without it a role loops on
    # read_file (worktree-relative) and never reads the evidence it just fetched.
    "read_offloaded": "read_offloaded",
    # Code navigation (read-only, tier 0): glob = find files by name/path shape, grep = find text by
    # regex, lsp = Python symbol intelligence (def/refs/hover — Python-only by design). Identity-mapped
    # dream built-ins (in default_registry), so dream_tool_names keeps them + _role_registry picks them
    # up. Offered platform-wide; a role admits only the ones that fit its worktree (a JS/TS frontend
    # role takes grep+glob but not lsp; a Python-writing role can take all three).
    "grep": "grep",
    "glob": "glob",
    "lsp": "lsp",
    # Analyst analysis tools (chorus-defined dream BaseTools; identity-mapped so dream_tool_names keeps
    # them and the subagent projection can intersect them — they are registered from ``analysis_tool``).
    "warehouse_query": "warehouse_query",
    "repo_search": "repo_search",
    "notebook_run": "notebook_run",
    "chart_render": "chart_render",
    # brand_lint is a chorus capability tool (registered via _capability_tool, NOT a dream built-in),
    # but it is IDENTITY-mapped here so the subagent projection (``_subagent_set`` → dream_tool_names ∩
    # parent) keeps it for the Brand-Critic (§08 owner). ``_role_registry`` still skips it (no built-in)
    # and ``_capability_tool`` registers it; the generator overlay is tools-unrestricted, so it's in the
    # parent's role-allowlist ceiling too. The MARKETER BRIEF must NOT instruct the parent to call it —
    # it is the critic's primitive; over-instructing the parent makes it mis-spawn brand_lint.
    "brand_lint": "brand_lint",
    # design_lint — the Designer's deterministic pre-gen scan (§08 tool / §10 sandwich): a chorus
    # capability tool (registered via _capability_tool, NOT a dream built-in), IDENTITY-mapped so the
    # subagent projection keeps it for the Design-Critic. The exact structural analog of brand_lint.
    "design_lint": "design_lint",
    # design_exemplar — the Designer's read-only exemplar fetcher (§08 tool): returns a vendored
    # real-world DESIGN.md from the design-md-exemplars library, which lives in the chorus package
    # (NOT the worktree), so a worktree-confined read_file can't reach it. A chorus capability tool
    # registered via _capability_tool; identity-mapped so dream_tool_names/projection keep it.
    "design_exemplar": "design_exemplar",
    # test_evidence — the Frontend Engineer's deterministic pre-done scan of its own test bundle: a
    # chorus capability tool (registered via _capability_tool, NOT a dream built-in), IDENTITY-mapped
    # so the subagent projection keeps it. The exact structural analog of design_lint (pure reader).
    "test_evidence": "test_evidence",
    # cms_draft — a chorus capability tool (reversible CMS write, §08 Channel). Identity-mapped for the
    # same reason as brand_lint: so the projection keeps it; it is registered in the materialize flow
    # (it needs the worktree for the Markdown backend, which _capability_tool has no access to).
    "cms_draft": "cms_draft",
    # execute_go_live — the §05 dark-node executor: publishes the staged draft ONLY once its
    # stage_go_live gate is APPROVED (fail-closed + idempotent). Registered in materialize (needs
    # ledger for the gate check + the worktree for the draft/delivery indexes).
    "execute_go_live": "execute_go_live",
}

_READ_ONLY_DREAM_SURFACE_TOOLS = frozenset(
    {
        "skill",
        "memory_search",
        "memory_get",
        "working_memory_read",
        # A read-only reviewer that reads a large artifact (a long findings.md) gets its read_file
        # output offloaded to scratch with a "Full output saved to: <file>" pointer; without
        # read_offloaded it cannot see the overflow and wrongly fails with "content is truncated /
        # cannot verify". read_offloaded is safe (tier-0, scratch-confined, read-only), so a verifier
        # head may hold it to read the full artifact it is judging.
        "read_offloaded",        # Code navigation is read-only (tier 0), so a read-only planner/evaluator head or reviewer may
        # hold it to locate + inspect code under review without mutating anything.
        "grep",
        "glob",
        "lsp",    }
)


def dream_tool_names(chorus_tools: tuple[str, ...]) -> tuple[str, ...]:
    """Map a role's chorus tool allow-list to dream built-in names, dropping chorus-only tools."""
    return tuple(_CHORUS_TO_DREAM_TOOL[name] for name in chorus_tools if name in _CHORUS_TO_DREAM_TOOL)


def _project_spec(spec: SubagentSpec, parent_tools: frozenset[str]) -> Subagent:
    """Project one chorus :class:`SubagentSpec` onto a dream :class:`Subagent`, recursively.

    Tools are mapped to dream names and intersected with ``parent_tools`` (narrower-wins). A spec's
    ``spawnable`` children (depth-2) are projected the same way against THIS spec's own effective
    tools, so the intersection chain holds transitively — a grandchild can only ever narrow.
    """
    tools = tuple(t for t in dream_tool_names(spec.tools) if t in parent_tools)
    own_tools = frozenset(tools)
    return Subagent(
        name=spec.name,
        description=spec.description,
        tools=tools,
        model=spec.model,
        max_turns=spec.max_turns,
        output_schema=spec.output_schema,
        spawnable=tuple(_project_spec(child, own_tools) for child in spec.spawnable),
    )


def _subagent_set(config: RoleBeatConfig) -> SubagentSet | None:
    """Project a role's chorus :class:`SubagentSpec`s onto a dream :class:`SubagentSet` (Tier-1).

    Each spec's chorus tool names are mapped to dream names and intersected with the parent role's
    own dream toolset, so a subagent can only ever *narrow* capability, never widen it (spec 06
    §minimisation). Returns ``None`` when the role declares no subagents, so the harness's tool surface
    stays byte-identical (``build_harness`` registers ``spawn_subagent`` only when a set is supplied).
    """
    if not config.subagents:
        return None
    parent_tools = frozenset(dream_tool_names(config.tools))
    agents = [_project_spec(spec, parent_tools) for spec in config.subagents]
    return build_subagent_set(tier1_agents=agents, parent_tools=parent_tools)


def _role_registry(dream_names: tuple[str, ...]) -> ToolRegistry:
    """A dream registry holding only the role's built-in tools — the harness's effective toolset."""
    full = default_registry()
    registry = ToolRegistry()
    for name in dream_names:
        tool = full.get(name)
        if tool is not None:
            registry.register(tool, source=ToolSource.DEFAULT)
    return registry


def _capability_tool(name: str, ledger: SqliteLedger | None) -> BaseTool | None:
    """Build the chorus capability tool for ``name``, or ``None`` if it isn't one.

    The ledger-bound tools require a live ``ledger``; the ledger-free ones (``brand_lint`` /
    ``design_lint`` / ``design_exemplar``) ignore it, so ``ledger`` may be ``None`` for those.
    """
    if name == "decompose":
        return DecomposeTool(ledger)
    if name == "submit_task":
        return SubmitTaskTool(ledger)
    if name == "assign_task":
        return AssignTaskTool(ledger)
    if name == "submit_verdict":
        return SubmitVerdictTool(ledger)
    if name == "stage_go_live":
        return GoLiveTool(ledger)
    if name == "brand_lint":
        return BrandLintTool()  # pure file reader — the ledger arg is unused (kept for a uniform seam)
    if name == "design_lint":
        return DesignLintTool()  # pure file reader — same uniform seam as brand_lint
    if name == "design_exemplar":
        return DesignExemplarTool()  # pure file reader over the vendored exemplar library
    if name == "test_evidence":
        return TestEvidenceTool()  # pure worktree reader — same uniform seam as design_lint
    return None


# Chorus capability tools that are pure file readers — they take no ledger (the arg is a uniform seam
# they ignore). They MUST register even in a ledger-free materialization (e.g. a standalone example
# runner or any path that builds the factory without a live ledger); otherwise a role silently loses
# them and the model, seeing them named in its brief but absent from its toolset, mis-routes (e.g.
# ``spawn_subagent(name="design_lint")`` or a worktree ``read_file`` of the exemplar path) and errors.
_LEDGER_FREE_CAPABILITY_TOOLS = frozenset(
    {"brand_lint", "design_lint", "design_exemplar", "test_evidence"}
)

# Capability tools that route work to *other* employees — a role holding one needs to know its reports.
_DELEGATING_TOOLS = frozenset({"decompose", "submit_task", "assign_task"})
# The manager's reactive tools on an integrate beat — withheld once the subtree is already complete.
_REACTIVE_TOOLS = frozenset({"submit_task", "assign_task"})


def _team_roster(ledger: SqliteLedger, *, exclude: str) -> str:
    """The employee's direct reports (id + role), so a delegator names valid assignees.

    When any report is itself a *manager*, the delegator is a director: it must hand each manager a
    whole self-contained AREA (a multi-file sub-goal) and let that manager sub-decompose — never a
    single file, and never dropping part of the goal. Without this the model collapses a multi-area
    goal into one file per manager (so whole areas are silently lost) and then, on integrate, re-submits
    the area a manager already delivered instead of the area that is still missing.
    """
    reports = [emp for emp in ledger.employees.list() if emp.reports_to == exclude]
    lines = [f"- {emp.id} ({emp.role})" for emp in reports]
    body = "\n".join(lines) if lines else "(no other employees are currently hired)"
    roster = (
        "\n\n## Your reports (assign each subtask's `assignee` to one of these employee ids)\n" + body
    )
    manager_reports = [emp for emp in reports if emp.role == "manager"]
    if manager_reports:
        ids = ", ".join(emp.id for emp in manager_reports)
        roster += (
            "\n\n## You are a director — delegate whole AREAS to your manager reports (" + ids + ")\n"
            "Some of your reports are themselves managers who run their own teams. Delegate a COMPLETE, "
            "self-contained AREA (a multi-file sub-goal) to each manager — NOT a single file — and let "
            "each manager sub-decompose its area into their own engineers. Do NOT break the goal down "
            "into individual files yourself, and do NOT create any files. Your decomposition MUST cover "
            "the ENTIRE goal: identify every distinct part it requires and assign EVERY part to exactly "
            "one manager — never drop, merge away, or forget a required area/module. Write each area "
            "child's `intent` as a full, standalone brief that names ALL the modules and behaviors that "
            "area must deliver.\n"
            "### Mapping rule (follow EXACTLY)\n"
            f"- You have these manager reports: {ids}. Create EXACTLY ONE area child task per manager "
            "report — so the number of child tasks you create EQUALS the number of managers above.\n"
            "- Map ONE distinct area to EACH manager: every manager listed MUST receive exactly one "
            "area child, and no manager may receive two. Assigning two children to the same manager (and "
            "leaving another manager with none) is WRONG — that is how whole areas get dropped.\n"
            "- Do NOT split ONE area's modules across multiple children: each area child must contain "
            "the COMPLETE set of modules the goal assigns to that area, never a subset. If the goal "
            "says an area has two modules, a child naming only one of them is a wrong per-file split. "
            "(An area the goal EXPLICITLY defines as a single integration module is fine — match the "
            "goal's own area definitions.)\n"
            "- Before you finish decomposing, verify: (a) one child per manager, (b) every manager has a "
            "child, (c) the four-or-more module files of the goal are all accounted for across your area "
            "children. If any check fails, re-form the children before finishing.\n"
            "On an integrate beat, if a required area is still missing or "
            "incomplete, `submit_task` the MISSING area to a manager — NEVER re-submit an area a manager "
            "already delivered, and never re-create files that already exist."
        )
    return roster


def _toml_escape(value: str) -> str:
    """Escape a string into a single-line TOML basic string (the overlay values are short)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def _toml_string_list(values: tuple[str, ...]) -> str:
    """Render a tuple of short strings as a TOML array."""
    return "[" + ", ".join(f'"{_toml_escape(value)}"' for value in values) + "]"


def _read_only_role_tools(
    role: Literal["planner", "evaluator"], config: RoleBeatConfig
) -> tuple[str, ...]:
    """Default read-only Dream role tools plus safe Engineer read surfaces."""
    base = default_role_manifest(role).tools or ()
    tools = list(base)
    for name in dream_tool_names(config.tools):
        if name in _READ_ONLY_DREAM_SURFACE_TOOLS and name not in tools:
            tools.append(name)
    return tuple(tools)


def write_role_overlays(harness_dir: Path, config: RoleBeatConfig) -> None:
    """Write planner/generator/evaluator overlays so the whole harness runs as the employee.

    Each overlay **appends** the employee's brief to that dream role's base prompt (keeping the role's
    orchestration instructions) and sets the employee's permission posture. ``run_task`` loads these
    from ``{working_dir}/.harness/roles/{role}.toml``.
    """
    roles_dir = harness_dir / ".harness" / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    for role in _DREAM_ROLES:
        base = default_role_manifest(role).system_prompt
        prompt = f"{base}\n\n## Operating brief (your role in the org)\n{config.system_prompt}"
        lines = [
            f'system_prompt = "{_toml_escape(prompt)}"',
            f'permission_mode = "{config.permission_mode}"',
        ]
        # The planner runs toolless on purpose. Given read-only tools and ``tool_choice="auto"``
        # (dream hardcodes auto), weaker models like gpt-5.4-mini emit a tool call and ZERO text —
        # so ``run_task`` finds no ``<spec>`` and fails with "planner reply missing <spec>".
        # (Verified directly against gpt-5.4-mini: tools+auto -> finish_reason=tool_calls, content
        # len 0; no tools / tool_choice=none -> a clean <spec>.) A toolless planner has nothing to
        # call, so it must emit the contract; the generator does the real exploration. The evaluator
        # keeps its read-only surfaces (it needs them to verify).
        if role == "planner":
            lines.append("tools = []")
        elif role == "evaluator":
            lines.append(f"tools = {_toml_string_list(_read_only_role_tools(role, config))}")
        (roles_dir / f"{role}.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_sandbox_config(harness_dir: Path, sandbox: str) -> None:
    """Write dream's ``.harness/sandbox.toml`` for the role's trust posture (spec 04 §4).

    dream double-gates ``unrestricted`` — it also needs ``confirm_unrestricted = true`` — so a role
    asking for it makes the deliberate, reviewable choice explicit. (Excluded from the branch by the
    workspace's ``info/exclude``.) The other guards — credential guard, command-deny, worktree
    confinement — apply at every tier.
    """
    harness = harness_dir / ".harness"
    harness.mkdir(parents=True, exist_ok=True)
    lines = [f'tier = "{sandbox}"']
    if sandbox == "unrestricted":
        lines.append("confirm_unrestricted = true")
    (harness / "sandbox.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mcp_allowlist(harness_dir: Path, servers: tuple[McpServerSpec, ...]) -> None:
    """Write dream's ``.harness/mcp-allowlist.toml`` — the MCP admission authority (spec 06).

    Only the servers the role declares are admitted; dream reads this file lazily on the first session
    and connects each ``[[mcp]]`` entry, registering its tools. A failed connect is non-fatal (recorded,
    not raised), so a missing runtime never aborts the beat. (Excluded from the branch by the
    workspace's ``info/exclude``.) No-op when the role declares no servers.
    """
    if not servers:
        return
    harness = harness_dir / ".harness"
    harness.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for server in servers:
        lines = [
            "[[mcp]]",
            f'name = "{_toml_escape(server.name)}"',
            f'endpoint = "{_toml_escape(server.endpoint)}"',
            f'transport = "{_toml_escape(server.transport)}"',
        ]
        if server.tier_required:
            lines.append(f'tier_required = "{_toml_escape(server.tier_required)}"')
        if server.tools:
            items = ", ".join(f'"{_toml_escape(tool)}"' for tool in server.tools)
            lines.append(f"tools = [{items}]")
        blocks.append("\n".join(lines))
    (harness / "mcp-allowlist.toml").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


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
        timeout_s: float | None = 90.0,
        ledger: SqliteLedger | None = None,
        trust_policy: TrustPolicy | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._deployment = deployment
        self._roles = roles
        self._pricing = pricing
        self._seed = seed
        self._timeout_s = timeout_s
        # §4 trust: the resolved per-beat preset narrows the harness at materialize (the empty default
        # gates nothing). It needs the live ledger to read the task's preset/boundary.
        self._trust_policy = trust_policy or TrustPolicy()
        # Capability tools (e.g. the manager's ``decompose``) mutate this ledger live during a beat.
        # Absent it, a role asking for one simply gets it dropped (fails closed, never crashes).
        self._ledger = ledger
        # The org's workspace root: .chorus/work/{org}/ — shared by chat, tick, and the `company`
        # console command (one identity), via the single dream-free `default_work_root` convention.
        base = work_root if work_root is not None else default_work_root()
        self._company_root = base / company_id

    @property
    def company_root(self) -> Path:
        """The org's workspace root (``.chorus/work/{org}/``) — where landers find the worktrees."""
        return self._company_root

    @property
    def landers(self) -> LanderRegistry:
        """The landing seam — the ``LanderRegistry`` the kernel lands passed beats through (spec 04 §2).

        Symmetric with :meth:`runner_for`: the factory owns execution, so it owns how each employee's
        deliverable lands. The consumer wires both at once —
        ``Chorus.build(..., beat_runner_for=factory.runner_for, landers=factory.landers)`` — instead of
        hand-building ``default_landers`` at every call site. The manager/reviewer landers come online
        only when the factory holds the live ledger they read from.
        """
        return default_landers(self._company_root, ledger=self._ledger)

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> BeatRunner:
        """The :class:`~chorus.heartbeat.BeatRunnerFor` seam — the role-faithful runner for a beat."""
        return self.materialize(employee, task_id=task_id).runner

    def review_runner_for(
        self, reviewer: Employee, *, task_id: str, worktree_owner_id: str
    ) -> BeatRunner:
        """The review seam — a read-only reviewer runner pointed at the author's worktree (M3 Reviewer)."""
        return self.materialize(
            reviewer, task_id=task_id, review_worktree_of=worktree_owner_id
        ).runner

    def materialize(
        self, employee: Employee, *, task_id: str | None = None, review_worktree_of: str | None = None
    ) -> EmployeeHarness:
        """Resolve ``employee``'s role into a configured dream harness in its isolated worktree.

        ``task_id`` shapes the harness to the beat's phase: a manager's **integrate** beat (its task
        already has children) is materialized **without** ``decompose``, so the model can react with
        ``submit_task`` / ``assign_task`` but cannot re-decompose a delegated subtree (M3 §5). The
        kickoff beat (no children yet) keeps ``decompose``.

        ``review_worktree_of`` points a (read-only) reviewer at another employee's worktree as its
        working dir, so it inspects the work under review *in place* — the verdict is rendered on the
        real diff, and the reviewer's read-only sandbox makes the borrowed worktree look-but-don't-touch.
        """
        if employee.role not in self._roles:
            raise ValueError(f"role {employee.role!r} for {employee.id!r} is not a registered role")
        manifest = self._roles.get(employee.role).manifest
        config = role_beat_config(manifest)

        # §4 trust: narrow the harness to the task's effective preset (read-only / plan for a low-trust
        # beat) and assert containment. A TrustDenied propagates — an uncontained beat is not built.
        task = (
            self._ledger.tasks.get(task_id)
            if task_id is not None and self._ledger is not None
            else None
        )
        config = apply_trust(config, task=task, policy=self._trust_policy)

        # Structural over-decompose guard: on an integrate beat the parent already owns children, so
        # ``decompose`` is dropped from the toolset entirely — the model never sees it (M3 §5). Brief
        # discipline alone is not enough; under load a manager re-decomposes and balloons the subtree.
        is_integrate_beat = (
            task_id is not None
            and self._ledger is not None
            and self._ledger.tasks.has_children(task_id)
        )
        if is_integrate_beat and "decompose" in config.tools:
            assert task_id is not None and self._ledger is not None  # narrowed by is_integrate_beat
            config = replace(config, tools=tuple(t for t in config.tools if t != "decompose"))
            # Structural over-submit guard: when the kernel's verdict is `accept` — every child done,
            # unblocked, and passing — the delegated work is complete, so submit_task/assign_task are
            # withheld too. The manager can only review and accept; it cannot bolt on redundant work.
            # (A live gpt-class manager over-submits even when the brief + packet tell it to accept.)
            if IntegrateContextPacket.recommended_for(self._ledger, task_id) == "accept":
                config = replace(
                    config, tools=tuple(t for t in config.tools if t not in _REACTIVE_TOOLS)
                )

        # Team rehydration: a delegating role (decompose/submit/assign) gets its reports appended to its
        # brief, read live from the workforce — so the model assigns to real employee ids, not invented.
        if self._ledger is not None and _DELEGATING_TOOLS.intersection(config.tools):
            roster = _team_roster(self._ledger, exclude=employee.id)
            config = replace(config, system_prompt=config.system_prompt + roster)

        # Operating environment: a role that RUNS commands (a build engineer) gets a factual runtime
        # block appended to its brief — the OS, the shell run_command lands on, and which build runtimes
        # (Node/npm/Playwright) are on PATH — so it writes portable commands and its DoD is known to be
        # platform-agnostic instead of guessed. dream advertises OS/shell/Python to every role already;
        # this adds the toolchain facts only a command-running role needs (doc/review roles run nothing).
        if "run_command" in config.tools:
            config = replace(
                config, system_prompt=config.system_prompt + "\n\n" + runtime_brief_block()
            )

        # ``working_dir`` IS the worktree, because dream confines its tools to it — that is what
        # isolates one employee's edits from another's. A non-worktree posture falls back to a flat
        # per-employee dir under the org root.
        workspace: CompanyWorkspace | None = None
        if config.isolation == "worktree":
            workspace = CompanyWorkspace(self._company_root, seed=self._seed)
            worktree_owner = review_worktree_of if review_worktree_of is not None else employee.id
            # Integrate beat: the manager delegated, so its worktree still sits at the ``main`` it
            # branched from — blind to the children's deliverables that have since landed. Sync it to
            # ``main`` first so the manager reviews the real, merged subtree instead of an empty tree
            # (read_file on the children's files would otherwise error and the verdict be vacuous).
            if is_integrate_beat and review_worktree_of is None:
                workspace.sync_to_main(worktree_owner)
            root = workspace.worktree_for(worktree_owner).path
        else:
            root = self._company_root / employee.id
        root.mkdir(parents=True, exist_ok=True)
        write_role_overlays(root, config)  # the employee's identity overlays the whole harness
        write_sandbox_config(root, config.sandbox)  # the role's trust posture → .harness/sandbox.toml
        # The role's admitted MCP servers → .harness/mcp-allowlist.toml (only when the role opts in via
        # ``mcp`` AND declares servers; dream connects them lazily on the first session).
        if config.mcp and config.mcp_servers:
            write_mcp_allowlist(root, config.mcp_servers)

        registry = _role_registry(dream_tool_names(config.tools))
        # Bind the role's chorus capability tools. The ledger-free ones (pure file readers:
        # design_lint / design_exemplar / brand_lint) register regardless — they need no ledger, and
        # withholding them when the factory has none is the bug that makes a role's own primitives
        # vanish from its toolset. The ledger-bound ones (decompose / submit_task / …) need the live
        # ledger and fail closed — dropped — when it is absent.
        for name in config.tools:
            if self._ledger is None and name not in _LEDGER_FREE_CAPABILITY_TOOLS:
                continue
            capability = _capability_tool(name, self._ledger)
            if capability is not None:
                registry.register(capability, source=ToolSource.DEFAULT)
        # cms_draft is registered here (not in _capability_tool): its Markdown fallback backend needs the
        # worktree, and the backend (Strapi when its env is set, else Markdown) is config-selected. No
        # ledger needed — a reversible CMS write, below the go-live gate.
        if "cms_draft" in config.tools:
            registry.register(
                CmsDraftTool(cms_backend_from_env(root / "cms_drafts")), source=ToolSource.DEFAULT
            )
        # execute_go_live pairs with cms_draft: it publishes the staged draft once the human approves
        # the stage_go_live gate. Needs BOTH the ledger (fail-closed gate check) and the worktree
        # (standing-draft + delivery indexes), so it registers here rather than in _capability_tool.
        if "execute_go_live" in config.tools and self._ledger is not None:
            registry.register(
                ExecuteGoLiveTool(
                    self._ledger,
                    publish_backend_from_env(root / "cms_drafts"),
                    email_delivery=email_delivery_from_env(root / "cms_drafts"),
                ),
                source=ToolSource.DEFAULT,
            )
        # Analysis tools (ledger-free, worktree-scoped): warehouse_query / repo_search / notebook_run /
        # chart_render. The generator runs tools=null, so registering them here is enough for the model
        # to see and call them; they are not dream built-ins, so _role_registry skipped them above.
        # (Web tools web_search/web_extract ARE dream built-ins, so _role_registry already picked them up.)
        for name in config.tools:
            atool = analysis_tool(name)
            if atool is not None and registry.get(name) is None:
                registry.register(atool, source=ToolSource.DEFAULT)

        # Subagents: project the role's Tier-1 declarations into dream's SubagentSet. The
        # spawn_subagent tool (already in the registry if "spawn_subagent" is in the role's tools)
        # discovers available subagents from this set at runtime.
        subagent_set = _subagent_set(config)

        # Every build_harness knob comes from the role config — this is where the employee *becomes*
        # its harness. config.model overrides the deployment when set; an empty role env means None.
        skill_registry = None
        if config.skills_root:
            skill_registry, _shadows = load_skill_registry(project_dirs=[Path(config.skills_root)])
        harness = dream.build_harness(
            model=config.model or self._deployment,
            api_key=self._api_key,
            base_url=self._base_url,
            working_dir=root,
            registry=registry,
            skills=bool(config.skills) or skill_registry is not None,
            skill_registry=skill_registry,
            memory=True,
            working_memory=config.working_memory,
            max_turns=config.max_turns,
            mcp=config.mcp,
            plugins=config.plugins,
            wake_model=config.wake_model,
            env=dict(config.env) or None,
            subagents=subagent_set,
        )
        return EmployeeHarness(
            runner=DreamBeatRunner(
                harness,
                pricing=self._pricing,
                max_sprints=config.max_sprints,  # the role's per-beat sprint budget (spec 05)
                # A research-heavy role widens its beat wall-clock past the org default (spec 06).
                timeout_s=config.beat_timeout_s if config.beat_timeout_s is not None else self._timeout_s,
                working_dir=root,
                employee_id=employee.id,  # stamped into each beat's context for capability tools
            ),
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
