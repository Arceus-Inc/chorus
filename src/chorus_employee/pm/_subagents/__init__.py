"""PM subagents — lean isolation earners Piper spawns mid-beat (pm design doc §06).

The Critic is the retained Tier-1 specialist: an adversarial red-team of the drafted
decision. Evidence gathering is ``web_research`` plus the ``evidence-brief`` skill on
the main employee — there is no researcher persona.

Typed research schemas remain available for tests and packet rendering; they are not
a spawnable roster entry.
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
    EvidenceItem,
    ResearchBrief,
    research_output_schema,
)

__all__ = [
    "CRITIC_SUBAGENT",
    "DecisionCritique",
    "Dimension",
    "EvidenceItem",
    "Finding",
    "ResearchBrief",
    "decision_critique_output_schema",
    "research_output_schema",
]
