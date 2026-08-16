"""The Frontend Engineer's dream-harness manifest — every ``build_harness`` component, in one place.

A Frontend Engineer **reads the intent + any existing code/design system; CHOOSES the stack that fits
(hand-written HTML/JS, a component framework, or a meta-framework); builds a working app in its worktree;
writes unit + real-browser e2e tests; RUNS them via ``run_command`` and captures the output into a
durable evidence bundle; and iterates until green**. So unlike the Designer (which writes a spec and runs
nothing), it needs **command execution** (Node, npm, a scaffolder, Playwright, a server) and **git** — an
autonomous build role. The role is framework-agnostic by construction: no stack is named in this file or
in the brief; framework specifics live only in the authored skills. Each field below names the dream
component it drives.

Slices layer in: the ``evidence_scan`` scan tool (a deterministic read-only view of the bundle), the
Code-Reviewer subagent (in-beat quality pressure, read-only), and the authored
build/testing craft skills (loaded on demand via the ``skill`` tool) are all wired here.
"""

from __future__ import annotations

import os
from pathlib import Path

from chorus.roles._manifest import (
    DREAM_DEFAULT_MAX_SPRINTS,
    Isolation,
    McpServerSpec,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.frontend_engineer._brief import FRONTEND_ENGINEER_BRIEF
from chorus_employee.frontend_engineer._subagents import CODE_REVIEWER_SUBAGENT

# Authored build/testing craft playbooks discovered from this package's ``skills/`` dir and offered on
# demand via the ``skill`` tool (mirrors the Designer's §08 skill library).
_SKILLS_ROOT = str(Path(__file__).parent / "skills")


def _browser_mcp_disabled() -> bool:
    """Operator escape hatch for a host where the Playwright MCP's ``npx`` stdio server *hangs* on
    connect (e.g. a first-run package/browser download stalling the handshake) rather than failing
    cleanly. dream's "failed connect is non-fatal" guard only covers a clean failure; a hang instead
    eats the whole beat budget every recovery cycle, wedging the build loop. Setting
    ``CHORUS_DISABLE_BROWSER_MCP`` omits the browser MCP so the beat still builds and runs the committed
    ``npx playwright test`` spec (the real DoD proof) — only the mid-build interactive scouting tool is
    dropped."""
    return os.environ.get("CHORUS_DISABLE_BROWSER_MCP", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def frontend_engineer_manifest() -> RoleManifest:
    """The complete harness identity of a Frontend Engineer (→ dream ``build_harness``)."""
    browser_mcp_off = _browser_mcp_disabled()
    return RoleManifest(
        # --- per-role overlay ---
        system_prompt=FRONTEND_ENGINEER_BRIEF,
        # ACCEPT_EDITS: it writes app code + tests + the evidence bundle to its worktree autonomously.
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # --- build_harness(registry=...) ---
        # Read + repo-write + run gates + git (a build role), plus durable/task memory and read-only web
        # research for API/pattern/a11y facts. test_evidence (the deterministic bundle scan) and
        # spawn_subagent (the Code-Reviewer review layer) is wired here; skill lands next.
        tools=(
            "read_file",
            # code navigation (read-only, tier 0): glob finds files by name/path shape, grep finds text
            # by regex — so the engineer locates its own source/tests/config precisely instead of blindly
            # re-reading. (dream's `lsp` is Python-only by design, so it is intentionally omitted: a
            # JS/TS/Vue/Svelte worktree has no Python target for it to resolve.)
            "grep",
            "glob",
            "write_file",
            "todo_write",  # durable cross-beat checklist (TODO.md) — resume, don't restart
            "run_command",
            "execute_code",
            "git",
            # deterministic read-only self-check of the test-evidence bundle before declaring done.
            "evidence_scan",
            # dispatch the Tier-1 review subagent (Code-Reviewer) after building + running.
            "spawn_subagent",
            "memory_search",
            "memory_get",
            "working_memory_read",
            "working_memory_write",
            "working_memory_append",
            "memory_propose",
            # read your own past episodic beats — recency/keyword, outcome attached
            # (spec 07 §11). The reasoning-recall counterpart to memory_search's durable facts.
            "recall",
            "lattice_context",
            "lattice_packet",
            "lattice_apply",
            "skill_manage",
            # Live web via Chromium CDP (docs, MDN, framework sites) — needs net tier below.
            "browser_run",
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
            # React/Next component, hook, state, and performance patterns (loaded if React is chosen).
            "frontend-patterns",
            "forms-and-validation",
            "unit-testing-with-node-test",
            "component-testing",
            "playwright-e2e-authoring",
            "web-first-assertions",
            "test-evidence-discipline",
            "debugging-failing-tests",
            "package-and-run-hygiene",
            # adapting the UI across screen sizes (breakpoints, container queries, fluid type, grid).
            "responsive-design",
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
        max_sprints=DREAM_DEFAULT_MAX_SPRINTS,
        # --- build_harness(mcp=...) / build_harness(plugins=...) ---
        # mcp is ON: the engineer admits the Playwright MCP (declared in ``mcp_servers`` below), so it
        # can drive a real browser INTERACTIVELY mid-build — navigate the running app, inspect the
        # accessibility tree, and discover robust locators — before committing the deterministic
        # ``npx playwright test`` spec that remains the after-beat gate. The committed e2e (re-run by the
        # DoD floor) is still the proof; the MCP is the scouting tool that makes that proof easier to
        # author. A failed connect is non-fatal (dream records it, never raises), so the beat is robust
        # even if the MCP runtime is unavailable on a given host. Operators can also omit it entirely on
        # a host where the ``npx`` stdio server *hangs* (rather than failing) via CHORUS_DISABLE_BROWSER_MCP.
        mcp=not browser_mcp_off,
        plugins=False,
        # The MCP servers this role admits → written to ``.harness/mcp-allowlist.toml`` at materialize.
        # Playwright's MCP is a local stdio server run via ``npx`` (the MCP SDK resolves ``npx``→
        # ``npx.cmd`` on Windows and spawns it through a platform-compatible process); ``--headless``
        # keeps it GUI-less for an autonomous beat and ``--isolated`` gives each session a fresh,
        # in-memory browser profile. The version is pinned so a future breaking release can't silently
        # change the tool surface. tier_required=repo_write keeps the browser tools above tier 0.
        mcp_servers=(
            ()
            if browser_mcp_off
            else (
                McpServerSpec(
                    name="playwright",
                    endpoint="stdio://npx @playwright/mcp@0.0.77 --headless --isolated",
                    transport="stdio",
                    tier_required="repo_write",
                ),
            )
        ),
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
        # Lean roster: code_reviewer only. UI proof audits → playwright/evidence skills + Dream verify.
        subagents=(CODE_REVIEWER_SUBAGENT,),
    )


__all__ = ["frontend_engineer_manifest"]
