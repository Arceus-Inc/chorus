"""Hermes-style tool-choice matrix for craft role briefs (S0 #10).

Hermes teaches *when* to call each orchestration surface (tool vs execute_code vs
delegate_task vs cron) instead of dumping every verb as equally good. Chorus maps
that schema onto the surfaces that exist today:

- direct **tool** call
- **skill** load (progressive disclosure)
- **spawn_subagent** (independent specialist / fresh judgment)
- **just implement** (you write / run / decide without spawning)

``execute_code`` is not a Chorus surface yet — mechanical multi-step maps to
calling tools yourself in sequence (``run_command``, lint/evidence tools, etc.).
"""

from __future__ import annotations

# Compact Use/Don't block (Hermes pattern). Keep short: briefs stay invariant;
# skills hold deep procedure (harness: context budget + action-space clarity).
TOOL_CHOICE_MATRIX = (
    "TOOL CHOICE (cheapest surface that fits):\n"
    "Use this                         Don't — use instead\n"
    "───────────────────────────────  ────────────────────────────────\n"
    "tool (read/write/run/lint/…)     spawn to wrap a single tool\n"
    "skill(name=…) for craft steps    invent procedure a skill covers\n"
    "spawn_subagent for named         spawn when tools+skills suffice\n"
    "  specialist / fresh judgment    spawn mechanical multi-step glue\n"
    "just implement yourself          durable across beats → TODO.md\n"
    "Rules: tool > skill > spawn. Spawn only for a typed specialist\n"
    "artifact you cannot honestly author alone."
)

__all__ = ["TOOL_CHOICE_MATRIX"]
