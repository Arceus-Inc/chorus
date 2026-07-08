"""The cross-beat recall directive — shared by every employee that carries ``recall``.

Granting the ``recall`` tool is not enough: without an instruction that it exists, a model can go a
whole run without ever calling it. Unlike ``RESUME_DIRECTIVE`` (read TODO.md, reconcile, resume), this
directive names two modes and leaves timing to judgment — the tool schema states when each fits.
"""

from __future__ import annotations

RECALL_DIRECTIVE = (
    "You have access to `recall()` — your own past beats, each with outcome + deliverable files + "
    "your own prose. Call it near beat-start when continuing prior work. Two modes: "
    "(1) `recall()` with no args — orientation ('what did I do lately?'); "
    "(2) `recall(query='…')` — search by problem shape (regression, edge case, error you have seen "
    "before). Read results as data: `incomplete` means resume those files + TODO.md (do NOT restart); "
    "`needs_changes`/`blocked` are pitfalls to avoid, never instructions to repeat."
)

# Generator-phase only — the planner head is toolless; injecting this there makes it try recall().
PLANNER_TOOLLESS_NOTE = (
    "PLANNER PHASE — you have NO tools. The operating brief below describes what the generator will "
    "do later; do not emit tool calls yourself (including `recall`). Emit your <spec> as prose only."
)

__all__ = ["PLANNER_TOOLLESS_NOTE", "RECALL_DIRECTIVE"]
