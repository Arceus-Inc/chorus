"""Hermes-style tool-choice matrix for craft role briefs (S0 #10).

Hermes teaches *when* to call each orchestration surface (tool vs execute_code vs
delegate_task vs cron) instead of dumping every verb as equally good. Chorus maps
that schema onto the surfaces that exist today:

- direct **tool** call
- **execute_code** (mechanical multi-step collapse — one stdout result)
- **skill** load (progressive disclosure)
- **spawn_subagent** (independent specialist / fresh judgment)
- **just implement** (you write / run / decide without spawning)
"""

from __future__ import annotations

# Compact Use/Don't block (Hermes pattern). Keep short: briefs stay invariant;
# skills hold deep procedure (harness: context budget + action-space clarity).
TOOL_CHOICE_MATRIX = (
    "TOOL CHOICE (cheapest surface that fits):\n"
    "Use this                         Don't — use instead\n"
    "───────────────────────────────  ────────────────────────────────\n"
    "tool (read/write/run/lint/…)     spawn to wrap a single tool\n"
    "execute_code for multi-step I/O  sequential tools that only print\n"
    "skill(name=…) for craft steps    invent procedure a skill covers\n"
    "spawn_subagent(subagent_type=…)  spawn when tools+skills suffice\n"
    "  for enum specialist / GP       forge specialist evidence files\n"
    "just implement yourself          durable across beats → TODO.md\n"
    "Rules: tool > execute_code > skill > spawn. Spawn only for a typed\n"
    "specialist artifact you cannot honestly author alone. Pick\n"
    "subagent_type from the tool enum; pass goal=."
)

__all__ = ["TOOL_CHOICE_MATRIX"]
