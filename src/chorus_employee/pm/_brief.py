"""The PM's operating brief — the system prompt this employee runs under.

A PM turns a goal or prompt into a written **plan / spec**: a concrete decision document a Reviewer
can verify and the org can build from. The composition root layers this onto each dream intra-task
role as a per-role overlay (see :func:`chorus_harness.write_role_overlays`).
"""

from __future__ import annotations

# The conventional file a PM writes its plan to, in its worktree. The lander snapshots this file as the
# ``doc`` artifact, so the brief and the lander must name the same path.
PM_PLAN_DOC = "plan.md"

PM_BRIEF = (
    "You are a product manager. Turn the task's goal into a clear, concrete written plan — scope, the "
    "decisions you are making, the approach, and the smallest set of next steps an engineer could pick "
    f"up. Write the plan to a single file named `{PM_PLAN_DOC}` in your working directory using "
    "`write_file`; that file IS your deliverable, so it must be present and non-empty. Read any "
    "existing material first with `read_file`. Be specific and decisive — a plan a Reviewer can judge "
    "against the task's intent, not a list of open questions."
)

__all__ = ["PM_BRIEF", "PM_PLAN_DOC"]
