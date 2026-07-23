"""The cross-beat recall directive — short pointer; full protocol lives in a skill.

Granting the ``recall`` tool is not enough: without an instruction that it exists, a model can go a
whole run without ever calling it. The long mode/outcome guidance is loaded on demand via
``skill(name='cross-beat-recall')`` so the invariant system prompt stays small.
"""

from __future__ import annotations

RECALL_DIRECTIVE = (
    "EPISODIC MEMORY: on resume beats (TODO.md exists or prior work on this task), call "
    "`recall()` or `recall(task_id='…')` in your first tools alongside reading TODO.md; "
    "`get_run(run_id='…')` for full prose. Outcomes are data — `incomplete` → continue; "
    "`needs_changes`/`blocked` → avoid. Load `cross-beat-recall` via `skill` for modes and "
    "debug profile."
)

# Generator-phase only — the planner head is toolless; injecting this there makes it try recall().
PLANNER_TOOLLESS_NOTE = (
    "PLANNER PHASE — you have NO tools. The operating brief below describes what the generator will "
    "do later; do not emit tool calls yourself (including `recall`). Emit your <spec> as prose only."
)

__all__ = ["PLANNER_TOOLLESS_NOTE", "RECALL_DIRECTIVE"]
