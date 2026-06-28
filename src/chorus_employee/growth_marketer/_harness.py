"""The Growth Marketer's dream-harness manifest — every ``build_harness`` component (spec GM §2, §6).

Mira **reads context, drafts copy, and writes her deliverable** (a report / brief / launch record):
she needs the file-read and file-write surfaces plus her durable + task memory, but no command
execution and no inline network — her external reach is the trust-scoped :mod:`._integrations`
WebPlugins, not raw host net, and her spend/send actions are fail-closed behind a human gate. Each
field below names the dream component it drives.
"""

from __future__ import annotations

from chorus.roles._manifest import (
    Isolation,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.growth_marketer._brief import GROWTH_MARKETER_BRIEF


def growth_marketer_manifest() -> RoleManifest:
    """The complete harness identity of a Growth Marketer (spec GM §2 → dream ``build_harness``)."""
    return RoleManifest(
        # — per-role overlay —
        system_prompt=GROWTH_MARKETER_BRIEF,  # → roles/{planner,generator,evaluator}.toml
        # ACCEPT_EDITS: she drafts and writes her deliverable autonomously (no human approves a
        # *draft*); the money-and-users actions are gated by her DoD, not by the file-write mode.
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # — build_harness(registry=…) —
        # read to gather context + draft, write to persist the deliverable, plus durable/task memory
        # so each stateless beat rehydrates the growth ledger and appends to it.
        tools=(
            "read_file",
            "write_file",
            "memory_search",
            "memory_get",
            "working_memory_read",
            "working_memory_write",
            "working_memory_append",
            "memory_propose",
        ),
        disallowed_tools=(),
        skills=(),  # the experiment-design / brand-voice playbooks (spec GM §6) ship as a follow-up
        # — build_harness(memory=…) + working_memory —
        memory_scope=MemoryScope.PROJECT,  # her growth memory scope — tribal knowledge (spec GM §12)
        working_memory=True,  # an in-task scratchpad across turns
        # — build_harness(max_turns=…) —
        max_turns=12,  # multi-step: read → segment → draft → design → evaluate
        # — per-beat sprint budget (spec 05) —
        max_sprints=4,  # a back-test may carry across sprints within one beat
        # — worktree containment (spec 04 §4) —
        isolation=Isolation.WORKTREE,
        # — trust posture (spec 04 §4) → .harness/sandbox.toml —
        # repo-write: writes files within her isolated worktree, runs no arbitrary host commands and
        # has no ambient net — external reach is the trust-scoped WebPlugin layer, gated separately.
        sandbox=SandboxTier.REPO_WRITE,
    )


__all__ = ["growth_marketer_manifest"]
