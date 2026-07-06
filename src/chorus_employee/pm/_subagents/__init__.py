"""PM subagents — the Tier-1 specialists Piper spawns mid-beat (pm design doc §06).

Each subagent is its own subpackage: the ``__init__`` carries the
:class:`~chorus.roles.SubagentSpec` and its sibling ``_schema`` module holds the pydantic-authored
return contract, emitted to the spec's ``output_schema`` so dream validates the child's final message
at runtime.

- **Researcher** (:mod:`._researcher`) — gathers and cites market/user evidence for a decision. It is
  depth-2 (spawns the shared ``web_research`` orchestrator) and returns a typed
  :class:`~...._researcher.ResearchBrief`. It gathers; the PM decides.

Tier-1, role-owned. Each spec's ``tools`` are CHORUS names (mapped to dream + intersected with the
PM's toolset at materialize, so a subagent can only ever narrow what its parent can do). Each spawned
child's system prompt is generated from name + description, so the full brief lives *in* the
description — imperative, so the specialist actually produces its deliverable.
"""

from __future__ import annotations

from chorus_employee.pm._subagents._critic import (
    CRITIC_SUBAGENT,
    DecisionCritique,
    Dimension,
    Finding,
    decision_critique_output_schema,
)
from chorus_employee.pm._subagents._researcher import (
    RESEARCHER_SUBAGENT,
    EvidenceItem,
    ResearchBrief,
    research_output_schema,
)

__all__ = [
    "CRITIC_SUBAGENT",
    "RESEARCHER_SUBAGENT",
    "DecisionCritique",
    "Dimension",
    "EvidenceItem",
    "Finding",
    "ResearchBrief",
    "decision_critique_output_schema",
    "research_output_schema",
]
