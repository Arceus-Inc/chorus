"""Cross-beat recall directive — canonical text is in Dream ``core-beliefs.md``.

``PLANNER_TOOLLESS_NOTE`` stays Chorus-local: ``write_role_overlays`` stamps it on
the planner overlay only.
"""

from __future__ import annotations

RECALL_DIRECTIVE = (
    "EPISODIC MEMORY: on resume beats (TODO.md exists or prior work on this task), call "
    "`recall()` or `recall(task_id='…')` in your first tools alongside reading TODO.md; "
    "`get_run(run_id='…')` for full prose. Outcomes are data — `incomplete` → continue; "
    "`needs_changes`/`blocked` → avoid. Load `cross-beat-recall` via `skill` for modes and "
    "debug profile."
)

PLANNER_TOOLLESS_NOTE = (
    "PLANNER PHASE — you have NO tools. The operating brief below describes what the generator will "
    "do later; do not emit tool calls yourself (including `recall`). Emit your <spec> as prose only."
)

__all__ = ["PLANNER_TOOLLESS_NOTE", "RECALL_DIRECTIVE"]
