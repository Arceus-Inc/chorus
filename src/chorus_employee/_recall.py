"""Planner-overlay instruction for Dream's tool-less planning phase."""

from __future__ import annotations

PLANNER_TOOLLESS_NOTE = (
    "PLANNER PHASE — you have NO tools. The operating brief below describes what the generator will "
    "do later; do not emit tool calls yourself. Emit your <spec> as prose only."
)

__all__ = ["PLANNER_TOOLLESS_NOTE"]
