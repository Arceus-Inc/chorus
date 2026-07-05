"""The Frontend Engineer's dream-harness manifest — every ``build_harness`` component, in one place.

A Frontend Engineer **reads the intent + any existing code/design system; CHOOSES the stack that fits
(hand-written HTML/JS, a component framework, or a meta-framework); builds a working app in its worktree;
writes unit + real-browser e2e tests; RUNS them via ``run_command`` and captures the output into a
durable evidence bundle; and iterates until green**. So unlike the Designer (which writes a spec and runs
nothing), it needs **command execution** (Node, npm, a scaffolder, Playwright, a server) and **git** — an
autonomous build role. The role is framework-agnostic by construction: no stack is named in this file or
in the brief; framework specifics live only in the authored skills. Each field below names the dream
component it drives.

Slices layer in: the ``test_evidence`` scan tool (a deterministic read-only view of the bundle), the
Code-Reviewer + UI-Tester subagents (in-beat quality pressure, both read-only), and the authored
build/testing craft skills (loaded on demand via the ``skill`` tool) are all wired here.
"""

from __future__ import annotations

from pathlib import Path

from chorus.roles._manifest import (
    Isolation,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.frontend_engineer._brief import FRONTEND_ENGINEER_BRIEF
from chorus_employee.frontend_engineer._subagents import (
    CODE_REVIEWER_SUBAGENT,
    UI_TESTER_SUBAGENT,
)

# Authored build/testing craft playbooks discovered from this package's ``skills/`` dir and offered on
# demand via the ``skill`` tool (mirrors the Designer's §08 skill library).
_SKILLS_ROOT = str(Path(__file__).parent / "skills")


def frontend_engineer_manifest() -> RoleManifest:
    """The complete harness identity of a Frontend Engineer (→ dream ``build_harness``)."""
    return RoleManifest(
        # --- per-role overlay ---
        system_prompt=FRONTEND_ENGINEER_BRIEF,
        # ACCEPT_EDITS: it writes app code + tests + the evidence bundle to its worktree autonomously.
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # --- build_harness(registry=...) ---
        # Read + repo-write + run gates + git (a build role), plus durable/task memory and read-only web
        # research for API/pattern/a11y facts. test_evidence (the deterministic bundle scan) and
        # spawn_subagent (the Code-Reviewer + UI-Tester review layer) are wired here; skill lands next.
        tools=(
            "read_file",
            "write_file",
            "run_command",
            "git",
            # deterministic read-only self-check of the test-evidence bundle before declaring done.
            "test_evidence",
            # dispatch the Tier-1 review subagents (Code-Reviewer, UI-Tester) after building + running.
            "spawn_subagent",
            "memory_search",
            "memory_get",
            "working_memory_read",
            "working_memory_write",
            "working_memory_append",
            "memory_propose",
            # read-only egress for grounding (MDN/WAI-ARIA/framework docs) — needs the net tier below.
            "web_search",
            "web_extract",
            # loads the authored build/testing craft playbooks on demand (spec-to-code, a11y, testing).
            "skill",
        ),
        disallowed_tools=(),
        # --- build_harness(skills=...) / build_harness(skill_registry=...) ---
        # Authored craft playbooks — durable, FRAMEWORK-AGNOSTIC know-how loaded on demand via the
        # `skill` tool, discovered from this package's skills/ dir. The neutral core (scoping, choosing
        # the stack, the pure/view seam, a11y, evidence, debugging, forms, packaging) plus stack-specific
        # playbooks (react-doctor, scaffolding-with-vite, component-testing) the engineer loads only if
        # it picks that stack. No stack is mandated; the choice + its playbooks are the engineer's.
        skills=(
            "spec-to-working-app",
            "choosing-a-frontend-stack",
            "semantic-html-and-aria",
            "keyboard-and-focus",
            "color-and-contrast",
            "state-driven-ui",
            "es-module-architecture",
            "scaffolding-with-vite",
            "react-doctor",
            "forms-and-validation",
            "unit-testing-with-node-test",
            "component-testing",
            "playwright-e2e-authoring",
            "web-first-assertions",
            "test-evidence-discipline",
            "debugging-failing-tests",
            "package-and-run-hygiene",
        ),
        skills_root=_SKILLS_ROOT,
        # --- build_harness(memory=...) + working_memory ---
        memory_scope=MemoryScope.PROJECT,
        working_memory=True,  # keeps a scratchpad of what was built / what failed across the build loop
        # --- build_harness(model=...) ---
        model=None,  # use the deployment model the composition root supplies
        wake_model=None,
        # --- build_harness(max_turns=...) ---
        # Build → unit-test → e2e-test → run → read failures → fix → re-run is deeply multi-step; 18 turns
        # leaves room for a couple of red→green iterations without starving the beat.
        max_turns=18,
        # --- per-beat sprint budget ---
        # A working+tested build is multi-sprint (draft, wire, test, converge); 6 lets one beat run the
        # build all the way to green rather than stopping mid-way and depending on re-dispatch.
        max_sprints=6,
        # --- build_harness(mcp=...) / build_harness(plugins=...) ---
        # mcp stays False deliberately (mirrors the gold-standard Designer deferring its Figma MCP): the
        # real-browser gate is already covered by `npx playwright test` run via run_command AND re-run by
        # the DoD floor, producing durable evidence — so a live per-beat `npx @playwright/mcp` connect
        # would add latency + a network dependency to every beat for no gate the deterministic e2e
        # doesn't already provide. Interactive MCP driving is a follow-up once the core loop is proven.
        mcp=False,
        plugins=False,
        # --- build_harness(env=...) ---
        env=(),
        # --- beat time budget (build + install + real-browser test runs) ---
        # A beat can hold an npm install, a Playwright run, and a couple of fix/re-run cycles; widen the
        # wall-clock well past the code-role defaults or the reaper claims the beat mid-test-run.
        beat_timeout_s=1800.0,
        lease_ttl_s=2100.0,
        # --- worktree containment ---
        isolation=Isolation.WORKTREE,
        # --- trust posture ---
        # UNRESTRICTED *within the isolated worktree*: it must run arbitrary commands (node, npm, npx
        # playwright, a static server) and reach the net to install Playwright — which dream otherwise
        # gates behind an interactive approval the kernel can't supply. dream's credential guard,
        # command-deny list, and worktree confinement still apply.
        sandbox=SandboxTier.UNRESTRICTED,
        # --- subagents (Tier-1, role-owned) ---
        # The post-build review layer: a Code-Reviewer (correctness / a11y / test integrity) and a
        # UI-Tester (auditor of the PROOF — does the e2e genuinely drive + assert the real UI). Both are
        # read-only (read_file / working_memory_read / test_evidence, all ⊆ this role's shelf), so the
        # projection keeps every tool; neither can edit or run, so the engineer keeps ownership of fixes.
        subagents=(
            CODE_REVIEWER_SUBAGENT,
            UI_TESTER_SUBAGENT,
        ),
    )


__all__ = ["frontend_engineer_manifest"]
