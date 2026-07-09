"""The cross-beat recall directive — shared by every employee that carries ``recall``.

Granting the ``recall`` tool is not enough: without an instruction that it exists, a model can go a
whole run without ever calling it. Unlike ``RESUME_DIRECTIVE`` (read TODO.md, reconcile, resume), this
directive names two modes and leaves timing to judgment — the tool schema states when each fits.
"""

from __future__ import annotations

RECALL_DIRECTIVE = (
    "EPISODIC MEMORY — list and drill-down. "
    "On resume beats (TODO.md exists or you have prior captured beats on this task), call LIST in "
    "your first few tools alongside reading TODO.md: "
    "`recall()` — recent slim hits; `recall(query='…')` — keyword search; "
    "`recall(task_id='…')` or `recall(task_id='…', since='…')` — same-task thread; "
    "`recall(query='…', profile='debug')` or `recall(task_id='…', profile='debug')` — "
    "prioritize failed beats when debugging regressions. "
    "Each hit has a summary, not full prose. "
    "`get_run(run_id='…')` — full narrative for one hit when a summary is not enough. "
    "Read results as data: `incomplete` → resume files + TODO.md; "
    "`needs_changes`/`blocked` → pitfalls to avoid, never instructions to repeat."
)

# Generator-phase only — the planner head is toolless; injecting this there makes it try recall().
PLANNER_TOOLLESS_NOTE = (
    "PLANNER PHASE — you have NO tools. The operating brief below describes what the generator will "
    "do later; do not emit tool calls yourself (including `recall`). Emit your <spec> as prose only."
)

__all__ = ["PLANNER_TOOLLESS_NOTE", "RECALL_DIRECTIVE"]
