"""Designer subagents — lean isolation earners Dara spawns mid-beat.

The Design-Critic is the retained Tier-1 specialist: a read-only adversarial
review of a spec against DESIGN.md and the accessibility floor. Framing and
variety live as skills (``user-flow-mapping``, layout playbooks) plus
``web_research`` on the main employee.

Typed explorer/UX-researcher schemas remain available for tests; they are not
spawnable roster entries.
"""

from __future__ import annotations

from chorus_employee.designer._subagents._design_critic import (
    DESIGN_CRITIC_SUBAGENT,
    DesignVerdict,
    DesignViolation,
    design_verdict_output_schema,
)
from chorus_employee.designer._subagents._explorer import (
    ExplorerManifest,
    VariantEntry,
    explorer_output_schema,
)
from chorus_employee.designer._subagents._ux_researcher import (
    EvidenceItem,
    UxBrief,
    ux_brief_output_schema,
)

__all__ = [
    "DESIGN_CRITIC_SUBAGENT",
    "DesignVerdict",
    "DesignViolation",
    "EvidenceItem",
    "ExplorerManifest",
    "UxBrief",
    "VariantEntry",
    "design_verdict_output_schema",
    "explorer_output_schema",
    "ux_brief_output_schema",
]
