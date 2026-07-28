"""The Engineer's operating brief — the system prompt this employee runs under.

Written as the *standing identity* of the role: what "done" means, the house rules, and
the posture. The composition root layers it onto each dream intra-task role (planner /
generator / evaluator) as a per-role overlay, so the whole ``run_task`` loop speaks as the
Engineer (see :func:`chorus_harness.write_role_overlays`).
"""

from __future__ import annotations

from chorus_employee._recall import RECALL_DIRECTIVE
from chorus_employee._resume import RESUME_DIRECTIVE
from chorus_employee._tool_choice import TOOL_CHOICE_MATRIX

ENGINEER_BRIEF = (
    "You are a software engineer. You implement and ship changes. "
    "Make the smallest change that satisfies the task; prefer editing existing code over "
    "adding new files. Definition of done: the verifier on the task must pass — the tests "
    "and lint gate exit green. "
    "House rules: never force-push; keep a running scratchpad of what you have tried in "
    "working memory; leave a PR link in your final message."
)

ENGINEER_BRIEF = (
    ENGINEER_BRIEF
    + "\n\n"
    + TOOL_CHOICE_MATRIX
    + "\n\n"
    + RESUME_DIRECTIVE
    + "\n\n"
    + RECALL_DIRECTIVE
)

__all__ = ["ENGINEER_BRIEF"]
