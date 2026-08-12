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

from chorus.adapters import DreamBeatRunner, TokenPricing, pricing_from_env_if_configured
from chorus.context import (
    LatticeWake,
    OperatingEnvironment,
    TaskContextPacket,
    operating_environment_from_platform,
    project_employee_wake,
    project_standalone_wake,
    project_task_context,
)
from chorus.heartbeat import BeatRunner, ExecutionProfileResolver, IntegrateContextPacket
from chorus.memory import EpisodicRecallService, EpisodicStore
from chorus.outcomes import LanderRegistry
from chorus.roles import RoleBeatConfig, RoleRegistry, role_beat_config
from chorus.roles._manifest import DEFAULT_BEAT_TIMEOUT_S, McpServerSpec
from chorus.roles._subagent import SubagentSpec
from chorus.trust import TrustPolicy
from chorus.workforce import Employee
from chorus.workspace import CompanyWorkspace, default_work_root
from chorus_employee import default_landers
from chorus_employee._lattice import LATTICE_SKILLS_ROOT, read_lattice_wake
from chorus_employee._shared_skills import SHARED_SKILLS_ROOT
from chorus_harness._company_state import write_company_state
from chorus_harness._dream_hooks import VolatileBeatPacket
from chorus_harness._env_capabilities import degrade_for_env
from chorus_harness._skills import materialize_skills, materialize_versioned_skills_into
from chorus_harness._trust import apply_trust
from chorus_tools import (
    AssignTaskTool,
    BrandLintTool,
    CodeQualityTool,
    CommentTool,
    DecomposeTool,
    DesignExemplarTool,
    DesignLintTool,
    EvidenceScanTool,
    GetRunTool,
    GoLiveTool,
    ReadCommentsTool,
    RecallTool,
    RecordDecisionTool,
    SecretScanTool,
    StaffingRequestTool,
    SubmitTaskTool,
    TeamReadTool,
    TestEvidenceTool,
    TestRedTool,
    WorkforceCatalogReadTool,
    WorkforcePlanProposeTool,
    analysis_tool,
    governance_tool,
)
from chorus_tools._lattice import _LATTICE_TOOLS, lattice_tool
from chorus_tools._lattice_bridge import build_lattice_for_chorus, write_lattice_error
from chorus_tools._skill_manage import SkillManageTool
from chorus_tools._todo_flush_nudge import registry_with_todo_flush_nudge
from chorus_tools.cms import CmsDraftTool, cms_backend_from_env
from chorus_tools.delivery import (
    ExecuteGoLiveTool,
    email_delivery_from_env,
    publish_backend_from_env,
)

if TYPE_CHECKING:
    from dream.contracts import GovernancePort
    from lattice.facade import Lattice

    from chorus.ledger import Ledger

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
    "edit_file": "apply_patch",
    "run_command": "bash",
    "execute_code": "execute_code",
    "git": "git",
    "skill": "skill",
    "memory_search": "memory_search",
    "memory_get": "memory_get",
    "working_memory_read": "working_memory_read",
    "working_memory_write": "working_memory_write",
    "working_memory_append": "working_memory_append",
    "memory_propose": "memory_propose",
    "spawn_subagent": "spawn_subagent",
    # Durable cross-beat checklist: dream's todo_write builtin atomically writes TODO.md to the worktree
    # (not in-context), so a re-dispatched beat resumes from it. Identity-mapped so dream_tool_names keeps
    # it and _role_registry enables it from default_registry.
    "todo_write": "todo_write",
    # Web research: first-class browser_run (Chromium CDP via browser-harness), plus
    # web_fetch (the lean direct-HTTP read — no CDP, no API key). Legacy Tavily
    # web_search/web_extract stay mapped so old manifests don't hard-fail during
    # migration, but employee roles grant browser_run / web_fetch only.
    "browser_run": "browser_run",
    "web_fetch": "web_fetch",
    "web_search": "web_search",
    "web_extract": "web_extract",
    # Reading spilled tool output: a large tool result (a browser_run dump, a repo_search dump) is
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
    # evidence_scan — the Frontend Engineer's deterministic pre-done scan of its own test_evidence/
    # bundle: a chorus capability tool (registered via _capability_tool, NOT a dream built-in),
    # IDENTITY-mapped so the subagent projection keeps it. The structural analog of design_lint (pure
    # reader). Distinct from the Backend Engineer's test_evidence gate-runner, which WRITES the bundle.
    "evidence_scan": "evidence_scan",
    # recall — a chorus capability tool (read-only episodic memory, spec 07 §11). Identity-mapped for
    # the same reason as evidence_scan: registered in the materialize flow (needs company_root), not
    # via _capability_tool, so it must stay in this map for the subagent projection to keep it.
    "recall": "recall",
    "get_run": "get_run",
    # comment / read_comments — the coordination verbs (OM-3): chorus capability tools
    # (registered via _capability_tool, need the ledger). Identity-mapped like record_decision
    # so dream_tool_names keeps them; rolled out to every ledger-backed employee in materialize
    # (the get_run precedent) — comments are communication, not authority; they run nothing.
    "comment": "comment",
    "read_comments": "read_comments",
    # lattice — semantic pattern consolidation (read-mostly; apply is gated). Identity-mapped like recall.
    "lattice_context": "lattice_context",
    "lattice_packet": "lattice_packet",
    "lattice_apply": "lattice_apply",
    "skill_manage": "skill_manage",
    # cms_draft — a chorus capability tool (reversible CMS write, §08 Channel). Identity-mapped for the
    # same reason as brand_lint: so the projection keeps it; it is registered in the materialize flow
    # (it needs the worktree for the Markdown backend, which _capability_tool has no access to).
    "cms_draft": "cms_draft",
    # test_evidence — the Backend Engineer's proof primitive (§10). Not a dream built-in; a pure
    # worktree runner (no ledger). IDENTITY-mapped so the subagent projection keeps it, and registered
    # UNCONDITIONALLY in the materialize flow below — the design_lint lesson: never behind the ledger
    # gate, so it always exists in a ledger-less run instead of being mis-routed as a subagent.
    "test_evidence": "test_evidence",
    "test_red": "test_red",
    "secret_scan": "secret_scan",
    "code_quality": "code_quality",
    # execute_go_live — the §05 dark-node executor: publishes the staged draft ONLY once its
    # stage_go_live gate is APPROVED (fail-closed + idempotent). Registered in materialize (needs
    # ledger for the gate check + the worktree for the draft/delivery indexes).
    "execute_go_live": "execute_go_live",
    # record_decision — the §10 Decision OS write: the PM records an immutable, cited decision as
    # ledger rows (via _capability_tool, needs the ledger). Identity-mapped so dream_tool_names keeps
    # it and the subagent projection can intersect it; _role_registry skips it (no built-in).
    "record_decision": "record_decision",
    # Governance tools — the CEO's reverse edge onto horizon's direction. Chorus capability tools bound
    # to a dream ``GovernancePort`` (registered in the materialize flow, NOT dream built-ins). IDENTITY-
    # mapped here for the same reason as record_decision/cms_draft: so ``dream_tool_names`` keeps them,
    # the role's per-phase allow-list ceiling admits them (else the planner phase projects ``<none>`` and
    # rejects governance_read as "not in this role's manifest"), and the subagent projection can carry
    # them. ``_role_registry`` still skips them (no built-in); the governance block in materialize binds
    # them to the injected port.
    "governance_read": "governance_read",
    "roadmap_propose": "roadmap_propose",
    "proposal_approve": "proposal_approve",
    "proposal_reject": "proposal_reject",
    "goal_set_priority": "goal_set_priority",
    "goal_archive": "goal_archive",
    "staffing_request": "staffing_request",
    "workforce_catalog_read": "workforce_catalog_read",
    "workforce_plan_propose": "workforce_plan_propose",
}

_READ_ONLY_DREAM_SURFACE_TOOLS = frozenset(
    {
        "skill",
        "memory_search",
        "memory_get",
        "working_memory_read",
        # recall is safe/read-only (chorus's own episodic counterpart to memory_search's durable
        # facts), so an evaluator verifying past-beat context needs it just as much as the generator.
        "recall",
        "get_run",
        # lattice_context is the read half of the lattice loop (consolidated patterns lookup) — safe
        # for a verifier head; the write half (lattice_apply / skill_manage) stays generator-only.
        "lattice_context",
        # A read-only reviewer that reads a large artifact (a long findings.md) gets its read_file
        # output offloaded to scratch with a "Full output saved to: <file>" pointer; without
        # read_offloaded it cannot see the overflow and wrongly fails with "content is truncated /
        # cannot verify". read_offloaded is safe (tier-0, scratch-confined, read-only), so a verifier
        # head may hold it to read the full artifact it is judging.
        "read_offloaded",  # Code navigation is read-only (tier 0), so a read-only planner/evaluator head or reviewer may
        # hold it to locate + inspect code under review without mutating anything.
        "grep",
        "glob",
        "lsp",
        # governance_read is read-only (risk=safe, tier 0): it only READS the company's direction through
        # the port. A read-only planner/evaluator head must be able to call it so the CEO can ground its
        # plan in the live tree before the generator phase acts. The mutating governance tools
        # (proposal_approve/reject, goal_set_priority/archive) are deliberately NOT here — they belong to
        # the generator phase only.
        "governance_read",
        "workforce_catalog_read",
        # read_comments is read-only/safe: a verifier judging "did the work address the thread"
        # must be able to read it. The write half (comment) stays generator-only.
        "read_comments",
    }
)


def dream_tool_names(chorus_tools: tuple[str, ...]) -> tuple[str, ...]:
    """Map a role's chorus tool allow-list to dream built-in names, dropping chorus-only tools."""
    return tuple(
        _CHORUS_TO_DREAM_TOOL[name] for name in chorus_tools if name in _CHORUS_TO_DREAM_TOOL
    )


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
        strict=spec.strict,
        spawnable=tuple(_project_spec(child, own_tools) for child in spec.spawnable),
    )


def _subagent_set(config: RoleBeatConfig) -> SubagentSet | None:
    """Project a role's chorus :class:`SubagentSpec`s onto a dream :class:`SubagentSet` (Tier-1).

    Each spec's chorus tool names are mapped to dream names and intersected with the parent role's
    own dream toolset, so a subagent can only ever *narrow* capability, never widen it (spec 06
    §minimisation). Returns ``None`` when the role has neither Specs nor ``spawn_subagent`` (tool
    surface stays byte-identical). Empty Specs + spawn tool → empty set (generalPurpose only).
    """
    if not config.subagents and "spawn_subagent" not in config.tools:
        return None
    parent_tools = frozenset(dream_tool_names(config.tools))
    agents = [_project_spec(spec, parent_tools) for spec in config.subagents]
    return build_subagent_set(tier1_agents=agents, parent_tools=parent_tools)


def _role_registry(dream_names: tuple[str, ...]) -> ToolRegistry:
    """A dream registry holding only the role's built-in tools — the harness's effective toolset."""
    full = default_registry()
    registry = ToolRegistry()
    names = dream_names
    if "read_file" in names and "read_offloaded" not in names:
        names = (*names, "read_offloaded")
    for name in names:
        tool = full.get(name)
        if tool is not None:
            registry.register(tool, source=ToolSource.DEFAULT)
    return registry


def _capability_tool(
    name: str,
    ledger: Ledger | None,
    roles: RoleRegistry,
) -> BaseTool | None:
    """Build the chorus capability tool for ``name``, or ``None`` if it isn't one.

    The ledger-bound tools require a live ``ledger``; the ledger-free ones (``brand_lint`` /
    ``design_lint`` / ``design_exemplar``) ignore it, so ``ledger`` may be ``None`` for those.
    """
    # Ledger-bound tools only build when a live ledger is present (the caller guarantees this via the
    # _LEDGER_FREE_CAPABILITY_TOOLS guard); the `is not None` check also narrows the type for mypy.
    if ledger is not None:
        if name == "decompose":
            return DecomposeTool(ledger)
        if name == "submit_task":
            return SubmitTaskTool(ledger)
        if name == "assign_task":
            return AssignTaskTool(ledger)
        if name == "team_read":
            return TeamReadTool(ledger)
        if name == "stage_go_live":
            return GoLiveTool(ledger)
        if name == "record_decision":
            return RecordDecisionTool(ledger)
        if name == "comment":
            return CommentTool(ledger)
        if name == "read_comments":
            return ReadCommentsTool(ledger)
        if name == "staffing_request":
            return StaffingRequestTool(ledger)
        if name == "workforce_catalog_read":
            return WorkforceCatalogReadTool(ledger, roles)
        if name == "workforce_plan_propose":
            return WorkforcePlanProposeTool(ledger, roles)
    if name == "brand_lint":
        return (
            BrandLintTool()
        )  # pure file reader — the ledger arg is unused (kept for a uniform seam)
    if name == "design_lint":
        return DesignLintTool()  # pure file reader — same uniform seam as brand_lint
    if name == "design_exemplar":
        return DesignExemplarTool()  # pure file reader over the vendored exemplar library
    if name == "evidence_scan":
        return (
            EvidenceScanTool()
        )  # Frontend Engineer's pure worktree scanner of the test_evidence/ bundle
    return None


# Chorus capability tools that are pure file readers — they take no ledger (the arg is a uniform seam
# they ignore). They MUST register even in a ledger-free materialization (e.g. a standalone example
# runner or any path that builds the factory without a live ledger); otherwise a role silently loses
# them and the model, seeing them named in its brief but absent from its toolset, mis-routes (e.g.
# ``spawn_subagent(subagent_type="design_lint")`` or a worktree ``read_file`` of the exemplar path) and errors.
_LEDGER_FREE_CAPABILITY_TOOLS = frozenset(
    {"brand_lint", "design_lint", "design_exemplar", "evidence_scan"}
)

# Capability tools that route work to *other* employees — a role holding one needs to know its reports.
_DELEGATING_TOOLS = frozenset({"decompose", "submit_task", "assign_task"})
# The manager's reactive tools on an integrate beat — withheld once the subtree is already complete.
_REACTIVE_TOOLS = frozenset({"submit_task", "assign_task"})


def _toml_escape(value: str) -> str:
    """Escape a string into a single-line TOML basic string (the overlay values are short)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def _toml_string_list(values: tuple[str, ...]) -> str:
    """Render a tuple of short strings as a TOML array."""
    return "[" + ", ".join(f'"{_toml_escape(value)}"' for value in values) + "]"


def _read_only_role_tools(
    role: Literal["planner", "evaluator"], config: RoleBeatConfig
) -> tuple[str, ...]:
    """Dream role tools for planner/evaluator plus safe employee read surfaces.

    Evaluator defaults include ``bash`` for in-session verify (no harness oracle).
    """
    base = default_role_manifest(role).tools or ()
    tools = list(base)
    for name in dream_tool_names(config.tools):
        if name in _READ_ONLY_DREAM_SURFACE_TOOLS and name not in tools:
            tools.append(name)
    return tuple(tools)


def write_agents_md(harness_dir: Path, config: RoleBeatConfig) -> None:
    """Materialize the employee brief as Dream context-tier ``AGENTS.md``.

    Dream loads ``.harness/AGENTS.md`` into the session ``<context>`` block.
    Phase identity (planner/generator/evaluator) lives in Dream standing orders.
    """
    harness = harness_dir / ".harness"
    harness.mkdir(parents=True, exist_ok=True)
    brief = (config.system_prompt or "").strip()
    (harness / "AGENTS.md").write_text(brief + ("\n" if brief else ""), encoding="utf-8")


def write_role_overlays(harness_dir: Path, config: RoleBeatConfig) -> None:
    """Write planner/generator/evaluator tool/permission overlays only.

    Employee craft identity is ``write_agents_md`` → ``.harness/AGENTS.md``.
    Dream standing orders own phase protocol; overlays must not mash briefs into
    ``system_prompt``. ``run_task`` loads these from
    ``{working_dir}/.harness/roles/{role}.toml``.
    """
    roles_dir = harness_dir / ".harness" / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    for role in _DREAM_ROLES:
        # Keep an empty system_prompt key so loaders that require the field stay happy;
        # Dream packaged standing orders supply phase text.
        lines = [
            'system_prompt = ""',
            f'permission_mode = "{config.permission_mode}"',
        ]
        # The planner runs toolless on purpose. Given read-only tools and ``tool_choice="auto"``
        # (dream hardcodes auto), weaker models like gpt-5.4-mini emit a tool call and ZERO text —
        # so ``run_task`` finds no ``<spec>`` and fails with "planner reply missing <spec>".
        # (Verified directly against gpt-5.4-mini: tools+auto -> finish_reason=tool_calls, content
        # len 0; no tools / tool_choice=none -> a clean <spec>.) A toolless planner has nothing to
        # call, so it must emit the contract; the generator does the real exploration. The evaluator
        # keeps reads + bash (in-session verify; no writers).
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
        timeout_s: float | None = DEFAULT_BEAT_TIMEOUT_S,
        ledger: Ledger | None = None,
        trust_policy: TrustPolicy | None = None,
        governance: GovernancePort | None = None,
        stop_evidence_requirements: bool = False,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._deployment = deployment
        self._roles = roles
        self._pricing = pricing if pricing is not None else pricing_from_env_if_configured()
        self._seed = seed
        self._timeout_s = timeout_s
        # §4 trust: the resolved per-beat preset narrows the harness at materialize (the empty default
        # gates nothing). It needs the live ledger to read the task's preset/boundary.
        self._trust_policy = trust_policy or TrustPolicy()
        # Capability tools (e.g. the manager's ``decompose``) mutate this ledger live during a beat.
        # Absent it, a role asking for one simply gets it dropped (fails closed, never crashes).
        self._ledger = ledger
        # The governance seam (the CEO's reverse edge onto horizon's direction). The composition root
        # wires this to horizon's control plane; chorus only ever sees the Port. Absent it, a role
        # asking for a governance tool simply gets it dropped — same fail-closed rule as the ledger.
        self._governance = governance
        # Lean Bex / Hermes default: parent implements; specialist evidence gates are opt-in.
        self._stop_evidence_requirements = stop_evidence_requirements
        # The org's workspace root: .chorus/work/{org}/ — shared by chat, tick, and the `company`
        # console command (one identity), via the single dream-free `default_work_root` convention.
        base = work_root if work_root is not None else default_work_root()
        self._company_root = base / company_id

    @property
    def company_root(self) -> Path:
        """The org's workspace root (``.chorus/work/{org}/``) — where landers find the worktrees."""
        return self._company_root

    def bind_governance(self, governance: GovernancePort) -> None:
        """Wire the governance seam onto this factory after construction (composition-root use).

        horizon's ``GovernancePort`` needs the ``org`` (hence this factory as its beat runner) to exist
        first, so it cannot be passed at construction. Binding it here lets the ONE factory that runs the
        beats give the CEO its governance tools (``governance_read`` / ``roadmap_propose`` / …). Non-CEO
        roles are unaffected — governance tools are manifest-gated, so only the CEO ever receives them.
        """
        self._governance = governance

    @property
    def landers(self) -> LanderRegistry:
        """The landing seam — the ``LanderRegistry`` the kernel lands passed beats through (spec 04 §2).

        Symmetric with :meth:`runner_for`: the factory owns execution, so it owns how each employee's
        deliverable lands. The consumer wires both at once —
        ``Chorus.build(..., beat_runner_for=factory.runner_for, landers=factory.landers)`` — instead of
        hand-building ``default_landers`` at every call site. The manager's subtree lander comes
        online only when the factory holds the live ledger it reads from.
        """
        return default_landers(self._company_root, ledger=self._ledger)

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> BeatRunner:
        """The :class:`~chorus.heartbeat.BeatRunnerFor` seam — the role-faithful runner for a beat."""
        return self.materialize(employee, task_id=task_id).runner

    def materialize(self, employee: Employee, *, task_id: str | None = None) -> EmployeeHarness:
        return self._materialize(employee, task_id=task_id)

    def _build_tool_registry(
        self,
        config: RoleBeatConfig,
        *,
        root: Path,
        lattice: Lattice | None,
    ) -> ToolRegistry:
        """Bind every chorus capability the role's manifest names onto dream's registry.

        One stanza per capability family; each is register-if-named and fail-closed on its
        own dependency (ledger, governance port, lattice), so a missing backend drops the
        tool rather than half-wiring it.
        """
        registry = _role_registry(dream_tool_names(config.tools))
        # Bind the role's chorus capability tools. The ledger-free ones (pure file readers:
        # design_lint / design_exemplar / brand_lint) register regardless — they need no ledger, and
        # withholding them when the factory has none is the bug that makes a role's own primitives
        # vanish from its toolset. The ledger-bound ones (decompose / submit_task / …) need the live
        # ledger and fail closed — dropped — when it is absent.
        for name in config.tools:
            if self._ledger is None and name not in _LEDGER_FREE_CAPABILITY_TOOLS:
                continue
            capability = _capability_tool(name, self._ledger, self._roles)
            if capability is not None:
                registry.register(capability, source=ToolSource.DEFAULT)
        # cms_draft is registered here (not in _capability_tool): its Markdown fallback backend needs the
        # worktree, and the backend (Strapi when its env is set, else Markdown) is config-selected. No
        # ledger needed — a reversible CMS write, below the go-live gate.
        if "cms_draft" in config.tools:
            registry.register(
                CmsDraftTool(cms_backend_from_env(root / "cms_drafts")), source=ToolSource.DEFAULT
            )
        # The governance tools (the CEO's reverse edge onto horizon) bind to the injected GovernancePort
        # rather than the ledger, so they register in their own block — independent of the ledger, gated
        # only on the port being present. Same fail-closed rule: no port ⇒ a role's governance tools are
        # simply dropped from its toolset.
        if self._governance is not None:
            for name in config.tools:
                gov_tool = governance_tool(name, self._governance)
                if gov_tool is not None:
                    registry.register(gov_tool, source=ToolSource.DEFAULT)
        # test_evidence (Backend Engineer §10): a pure worktree runner — it runs the discovered verify
        # commands via the execution context and writes the test_evidence/ bundle. No ledger, so it
        # registers UNCONDITIONALLY (not behind the `self._ledger is not None` gate) — the design_lint fix.
        if "test_evidence" in config.tools:
            registry.register(TestEvidenceTool(), source=ToolSource.DEFAULT)
        if "test_red" in config.tools:
            registry.register(TestRedTool(), source=ToolSource.DEFAULT)
        # secret_scan is the same shape: a pure worktree scanner that reads files + writes the
        # security_scan/ report. No ledger, so it registers UNCONDITIONALLY too.
        if "secret_scan" in config.tools:
            registry.register(SecretScanTool(), source=ToolSource.DEFAULT)
        # code_quality: a stack-blind executor that runs the discovered fmt/lint/type checks + writes
        # the durable code_quality/ report. No ledger — registers UNCONDITIONALLY, like the above.
        if "code_quality" in config.tools:
            registry.register(CodeQualityTool(), source=ToolSource.DEFAULT)
        # recall (spec 07 §11): read your OWN past episodic beats — recency/keyword. No
        # ledger; rooted at the ORG's memory dir (company_root/memory), not the per-employee worktree
        # — episodic capture is one shared SQLite store for the whole company.
        if "recall" in config.tools:
            episodic = EpisodicRecallService(EpisodicStore(self._company_root / "memory"))
            registry.register(RecallTool(episodic), source=ToolSource.DEFAULT)
            registry.register(GetRunTool(episodic), source=ToolSource.DEFAULT)
        # lattice tools: read consolidated patterns (context), build the consolidation packet, apply
        # adjudicated proposals. Reuses the lattice built (or not) at beat start above. Advisory like
        # the adjudicate step: a broken lattice skips these tools (with a breadcrumb), never the beat.
        if _LATTICE_TOOLS.intersection(config.tools):
            if lattice is None:
                try:
                    lattice = build_lattice_for_chorus(
                        self._company_root,
                        canonical_skills_root=config.skills_root,
                    )
                except Exception as exc:
                    write_lattice_error(root, site="materialize.tool_registration", error=exc)
            if lattice is not None:
                for name in _LATTICE_TOOLS.intersection(config.tools):
                    tool = lattice_tool(name, lattice)
                    if tool is not None:
                        registry.register(tool, source=ToolSource.DEFAULT)
        if "skill_manage" in config.tools and self._ledger is not None:
            registry.register(
                SkillManageTool(
                    company_root=self._company_root,
                    ledger=self._ledger,
                    canonical_skills_root=(
                        Path(config.skills_root) if config.skills_root else None
                    ),
                ),
                source=ToolSource.DEFAULT,
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
        # (browser_run / legacy web_* ARE dream built-ins, so _role_registry already picked them up.)
        for name in config.tools:
            atool = analysis_tool(name)
            if atool is not None and registry.get(name) is None:
                registry.register(atool, source=ToolSource.DEFAULT)

        if "todo_write" in config.tools:
            registry = registry_with_todo_flush_nudge(registry)
        return registry

    def _materialize(
        self,
        employee: Employee,
        *,
        task_id: str | None = None,
    ) -> EmployeeHarness:
        """Resolve ``employee``'s role into a configured dream harness in its isolated worktree.

        ``task_id`` shapes the harness to the beat's phase: a manager's **integrate** beat (its task
        already has children) is materialized **without** ``decompose``, so the model can react with
        ``submit_task`` / ``assign_task`` but cannot re-decompose a delegated subtree (M3 §5). The
        kickoff beat (no children yet) keeps ``decompose``.
        """
        if employee.role not in self._roles:
            raise ValueError(f"role {employee.role!r} for {employee.id!r} is not a registered role")

        # §4 trust: narrow the harness to the task's effective preset (read-only / plan for a low-trust
        # beat) and assert containment. A TrustDenied propagates — an uncontained beat is not built.
        task = (
            self._ledger.tasks.get(task_id)
            if task_id is not None and self._ledger is not None
            else None
        )
        if self._ledger is None:
            config = role_beat_config(self._roles.get(employee.role).manifest)
        else:
            profile = ExecutionProfileResolver(self._roles, self._ledger).resolve(employee, task)
            config = profile.config
        config = apply_trust(config, task=task, policy=self._trust_policy)
        # Env-capability degradation (H2): a tool this environment cannot back (browser_run with no
        # Chromium CDP endpoint) is dropped and disclosed in the brief — the beat still runs.
        config = degrade_for_env(config)
        inbox_ids: tuple[str, ...] = ()
        task_context: TaskContextPacket | None = None
        include_reports = bool(_DELEGATING_TOOLS.intersection(config.tools))
        runtime: OperatingEnvironment | None = (
            operating_environment_from_platform() if "run_command" in config.tools else None
        )

        # Persisted contract status selects the phase-specific management tools in the execution
        # profile. Child presence is retained only for worktree synchronization and the completed
        # subtree guard; it is not an authority source.
        is_integrate_beat = (
            task_id is not None
            and self._ledger is not None
            and self._ledger.tasks.has_children(task_id)
        )
        if is_integrate_beat:
            assert task_id is not None and self._ledger is not None  # narrowed by is_integrate_beat
            # Structural over-submit guard: when the kernel's verdict is `accept` — every child done,
            # unblocked, and passing — the delegated work is complete, so submit_task/assign_task are
            # withheld too. The manager can only review and accept; it cannot bolt on redundant work.
            # (A live gpt-class manager over-submits even when the brief + packet tell it to accept.)
            if IntegrateContextPacket.recommended_for(self._ledger, task_id) == "accept":
                config = replace(
                    config, tools=tuple(t for t in config.tools if t not in _REACTIVE_TOOLS)
                )

        if "recall" in config.tools and "get_run" not in config.tools:
            config = replace(config, tools=(*config.tools, "get_run"))

        # OM-3: every ledger-backed EMPLOYEE gets the coordination verbs (the get_run precedent —
        # comments are communication, not authority: they run nothing). And the inbox IS the brief
        # (paperclip: inbox = assigned tasks + comments): unread messages land in the operating
        # brief and are consumed, so the thread stays readable via read_comments but the nudge
        # never repeats.
        if self._ledger is not None and self._ledger.employees.get(employee.id) is not None:
            missing = tuple(t for t in ("comment", "read_comments") if t not in config.tools)
            if missing:
                config = replace(config, tools=(*config.tools, *missing))

        # ``working_dir`` IS the worktree, because dream confines its tools to it — that is what
        # isolates one employee's edits from another's. A non-worktree posture falls back to a flat
        # per-employee dir under the org root.
        workspace: CompanyWorkspace | None = None
        if config.isolation == "worktree":
            workspace = CompanyWorkspace(self._company_root, seed=self._seed)
            # Integrate beat: the manager delegated, so its worktree still sits at the ``main`` it
            # branched from — blind to the children's deliverables that have since landed. Sync it to
            # ``main`` first so the manager reviews the real, merged subtree instead of an empty tree
            # (read_file on the children's files would otherwise error and the verdict be vacuous).
            if is_integrate_beat:
                workspace.sync_to_main(employee.id)
            root = workspace.worktree_for(employee.id).path
        else:
            root = self._company_root / employee.id
        root.mkdir(parents=True, exist_ok=True)

        # Lattice sleep-as-verifier (integration §4.4): adjudicate fresh episodes at beat START.
        # Gate-open teaser rides the TCP lattice_wake field (skills own the cookbook).
        lattice = None
        lattice_wake: LatticeWake | None = None
        if _LATTICE_TOOLS.intersection(config.tools):
            try:
                lattice = build_lattice_for_chorus(
                    self._company_root,
                    canonical_skills_root=config.skills_root,
                )
                if lattice.has_fresh_episodes(employee.id):
                    lattice.adjudicate(employee.id)
            except Exception as exc:
                lattice = None
                write_lattice_error(root, site="materialize.adjudicate", error=exc)
            lattice_wake = read_lattice_wake(root)

        if self._ledger is not None and task is not None:
            task_context = project_task_context(
                self._ledger,
                task_id=task.id,
                employee=employee,
                include_reports=include_reports,
                team_id=task.team_id,
                runtime=runtime,
                lattice_wake=lattice_wake,
            )
            inbox_ids = tuple(item.id for item in task_context.inbox)
        elif self._ledger is not None and (include_reports or runtime is not None or lattice_wake):
            task_context = project_employee_wake(
                self._ledger,
                employee=employee,
                include_reports=include_reports,
                team_id=task.team_id if task is not None else None,
                runtime=runtime,
                lattice_wake=lattice_wake,
            )
            inbox_ids = tuple(item.id for item in task_context.inbox)
        elif runtime is not None or lattice_wake is not None:
            task_context = project_standalone_wake(
                employee_id=employee.id,
                runtime=runtime,
                lattice_wake=lattice_wake,
            )

        write_agents_md(root, config)  # employee brief → Dream <context> AGENTS.md
        write_role_overlays(root, config)  # tools / permission_mode only
        write_sandbox_config(
            root, config.sandbox
        )  # the role's trust posture → .harness/sandbox.toml
        # The role's admitted MCP servers → .harness/mcp-allowlist.toml (only when the role opts in via
        # ``mcp`` AND declares servers; dream connects them lazily on the first session).
        if config.mcp and config.mcp_servers:
            write_mcp_allowlist(root, config.mcp_servers)

        registry = self._build_tool_registry(config, root=root, lattice=lattice)

        # Subagents: project the role's Tier-1 declarations into dream's SubagentSet. The
        # spawn_subagent tool (already in the registry if "spawn_subagent" is in the role's tools)
        # discovers available subagents from this set at runtime.
        subagent_set = _subagent_set(config)

        # Every build_harness knob comes from the role config — this is where the employee *becomes*
        # its harness. config.model overrides the deployment when set; an empty role env means None.
        # Skills: materialize the role's bundle *into* the worktree (read-only, git-excluded) so the
        # model can reach the bundled reference files with its worktree-confined read_file — then point
        # dream's registry at that in-worktree copy, so SKILL.md load and reference reads share a path.
        skill_registry = None
        # Lattice-carrying roles also get the lattice playbooks (lattice-context/lattice-consolidate)
        # merged in as another shared root — same transport as cross-beat-recall, no extra mechanism.
        # A role WITHOUT lattice tools must not see them: a skill telling you to call lattice_context
        # when the tool isn't in your manifest is harmful guidance.
        has_lattice = bool(_LATTICE_TOOLS.intersection(config.tools))
        extra_roots = (
            (SHARED_SKILLS_ROOT, LATTICE_SKILLS_ROOT) if has_lattice else (SHARED_SKILLS_ROOT,)
        )
        if config.skills_root:
            skills_dir = materialize_skills(
                root,
                config.skills_root,
                extra_roots=extra_roots,
            )
            if has_lattice and self._ledger is not None:
                # SkillStore HEAD (evolved/created procedural skills) overlays the canonical bundle —
                # the DB is the source of truth; this materialized copy is the per-beat cache.
                materialize_versioned_skills_into(
                    skills_dir,
                    ledger=self._ledger,
                    company_root=self._company_root,
                    employee_id=employee.id,
                )
            skill_registry, _shadows = load_skill_registry(project_dirs=[skills_dir])
        # Free-run checklist #5: an executive beat receives the company state it must review —
        # ledger truth mirrored as a citable worktree file (governance_read = the signature).
        if self._ledger is not None and "governance_read" in config.tools:
            write_company_state(self._ledger, root)

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
            web=True,
            browser=True,
            code_intel=True,
            max_turns=config.max_turns,
            mcp=config.mcp,
            plugins=config.plugins,
            wake_model=config.wake_model,
            env=dict(config.env) or None,
            subagents=subagent_set,
        )
        # S1 #2 / #11: powered dream hooks — dangerous-tool veto + evidence continue.
        from chorus_harness._dream_hooks import register_employee_hooks

        def consume_inbox() -> None:
            if self._ledger is None:
                return
            for message_id in inbox_ids:
                self._ledger.messages.mark_read(message_id)

        register_employee_hooks(
            harness,
            working_dir=root,
            subagents=config.subagents,
            stop_evidence_requirements=self._stop_evidence_requirements,
            volatile_packet=VolatileBeatPacket(
                task_context=task_context,
                on_injected=consume_inbox if inbox_ids else None,
            ),
        )
        evidence_specs = {
            spec.name: (
                spec.evidence_path,
                spec.evidence_claim,
                spec.evidence_read_only,
            )
            for spec in config.subagents
            if spec.evidence_path is not None and spec.evidence_claim is not None
        }
        return EmployeeHarness(
            runner=DreamBeatRunner(
                harness,
                pricing=self._pricing,
                max_sprints=config.max_sprints,  # the role's per-beat sprint budget (spec 05)
                # A research-heavy role widens its beat wall-clock past the org default (spec 06).
                timeout_s=config.beat_timeout_s
                if config.beat_timeout_s is not None
                else self._timeout_s,
                working_dir=root,
                employee_id=employee.id,  # stamped into each beat's context for capability tools
                subagent_evidence=evidence_specs,
            ),
            workspace=workspace,
            working_dir=root,
            config=config,
        )


__all__ = [
    "EmployeeHarness",
    "EmployeeHarnessFactory",
    "dream_tool_names",
    "write_agents_md",
    "write_role_overlays",
]
