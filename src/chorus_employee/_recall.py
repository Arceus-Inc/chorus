"""Cross-beat recall directive — re-export from Dream's Base Prompt.

Canonical ``RECALL_DIRECTIVE`` lives in ``dream.prompts.employee_base`` and is
injected by Dream when ``employee_mode=True``. ``PLANNER_TOOLLESS_NOTE`` stays
here: Chorus ``write_role_overlays`` stamps it on the planner overlay only.
"""

from __future__ import annotations

from dream.prompts.employee_base import RECALL_DIRECTIVE

# Generator-phase only — the planner head is toolless; injecting recall/tool
# guidance there makes it try tool calls. Dream's Base Prompt already omits
# those blocks when tools=[]: this note is an explicit planner-phase guard.
PLANNER_TOOLLESS_NOTE = (
    "PLANNER PHASE — you have NO tools. The operating brief below describes what the generator will "
    "do later; do not emit tool calls yourself (including `recall`). Emit your <spec> as prose only."
)

__all__ = ["PLANNER_TOOLLESS_NOTE", "RECALL_DIRECTIVE"]
