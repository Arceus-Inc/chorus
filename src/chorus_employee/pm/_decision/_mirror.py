"""The canonical ``decision.json`` shape — the one place the mirror's contract is named (§10).

``decision.json`` is the worktree mirror of a recorded decision: the DoD floor's deterministic check
surface and a human-diffable record. Both the ``record_decision`` tool (mid-beat) and the PM lander
(re-derived from the ledger at landing) write it, so the shape lives here once (checklist C14) and can
never drift between the two writers.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chorus.ledger._models import Claim, DecisionRecord

DECISION_MIRROR_DOC = "decision.json"


def render_decision_mirror(record: DecisionRecord, claims: Sequence[Claim]) -> dict[str, Any]:
    """Project an immutable ``DecisionRecord`` + its ``Claim`` rows into the ``decision.json`` payload."""
    return {
        "decision_id": record.id,
        "option": record.option,
        "rationale": record.rationale,
        "confidence": record.confidence,
        "outcome_metric": record.outcome_metric,
        "revisit_trigger": record.revisit_trigger,
        "rejected_alternatives": [
            {"option": rejected.option, "reason": rejected.reason}
            for rejected in record.rejected_alternatives
        ],
        "claims": [
            {"text": claim.text, "source_url": claim.source_url, "confidence": claim.confidence}
            for claim in claims
        ],
    }


__all__ = ["DECISION_MIRROR_DOC", "render_decision_mirror"]
