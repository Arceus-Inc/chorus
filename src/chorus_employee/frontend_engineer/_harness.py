"""The Frontend Engineer's dream-harness manifest — every ``build_harness`` component, in one place.

A Frontend Engineer **reads the intent + any existing code/design system; builds a working static web app
in its worktree; writes unit + real-browser e2e tests; RUNS them via ``run_command`` and captures the
output into a durable evidence bundle; and iterates until green**. So unlike the Designer (which writes a
spec and runs nothing), it needs **command execution** (Node, npm, Playwright, a static server) and
**git** — an autonomous build role. Each field below names the dream component it drives.

Slices layer in: the ``test_evidence`` scan tool (a deterministic read-only view of the bundle), the
UI-Tester + Code-Reviewer subagents (in-beat quality pressure) with the Playwright MCP they drive, and the
authored build/testing craft skills.
"""

from __future__ import annotations

from chorus.roles._manifest import (
    Isolation,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.frontend_engineer._brief import FRONTEND_ENGINEER_BRIEF


def frontend_engineer_manifest() -> RoleManifest:
    """The complete harness identity of a Frontend Engineer (→ dream ``build_harness``)."""
    return RoleManifest(
        # --- per-role overlay ---
        system_prompt=FRONTEND_ENGINEER_BRIEF,
        # ACCEPT_EDITS: it writes app code + tests + the evidence bundle to its worktree autonomously.
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # --- build_harness(registry=...) ---
        # Read + repo-write + run gates + git (a build role), plus durable/task memory and read-only web
        # research for API/pattern/a11y facts. The test_evidence scan tool, spawn_subagent, and skill are
        # added in later slices as their backing pieces land.
        tools=(
            "read_file",
            "write_file",
            "run_command",
            "git",
            "memory_search",
            "memory_get",
            "working_memory_read",
            "working_memory_write",
            "working_memory_append",
            "memory_propose",
            # read-only egress for grounding (MDN/WAI-ARIA/framework docs) — needs the net tier below.
            "web_search",
            "web_extract",
        ),
        disallowed_tools=(),
        # --- build_harness(skills=...) / build_harness(skill_registry=...) ---
        skills=(),  # authored build/testing craft playbooks land in a later slice
        skills_root=None,
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
        mcp=False,  # the Playwright MCP (interactive UI driving) is wired in the subagent slice
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
        subagents=(),  # UI-Tester + Code-Reviewer + Web-Research land in the subagent slice
    )


__all__ = ["frontend_engineer_manifest"]
