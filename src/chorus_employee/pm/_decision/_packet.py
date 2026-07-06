"""The decision packet — ``sources.json`` projected from the Decision OS rows (pm design doc §10).

A deterministic read model, no model in the loop: every decision recorded for the task with its cited
evidence ids and supersede pointer, plus every source with the decisions that rest on it. Claims are
read in one batched query (:meth:`ClaimRepo.for_decisions`), so a packet over many decisions never
becomes N+1. This is what §07's gated publish ships and what makes a recommendation auditable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger
    from chorus.ledger._models import Claim

_EXPORT_SCOPE = "team"


def render_packet(ledger: SqliteLedger, task_id: str) -> dict[str, Any]:
    """Project the task's decisions + claims into the ``sources.json`` packet contract (v1)."""
    decisions = ledger.decisions.for_task(task_id)
    claims = ledger.claims.for_decisions([decision.id for decision in decisions])
    claims_by_decision = _group_by_decision(claims)

    decision_entries = [
        {
            "id": decision.id,
            "option": decision.option,
            "confidence": decision.confidence,
            "evidenceIds": sorted(claim.id for claim in claims_by_decision.get(decision.id, [])),
            "supersededBy": decision.superseded_by,
        }
        for decision in decisions
    ]
    return {
        "decisions": decision_entries,
        "sources": _sources(claims),
        "exportScope": _EXPORT_SCOPE,
    }


def _group_by_decision(claims: list[Claim]) -> dict[str, list[Claim]]:
    grouped: dict[str, list[Claim]] = {}
    for claim in claims:
        grouped.setdefault(claim.decision_id, []).append(claim)
    return grouped


def _sources(claims: list[Claim]) -> list[dict[str, Any]]:
    """One entry per distinct source URL, with the decisions that cite it (sorted, deterministic)."""
    cited: dict[str, set[str]] = {}
    for claim in claims:
        cited.setdefault(claim.source_url, set()).add(claim.decision_id)
    return [
        {"uri": uri, "citedInDecisions": sorted(decision_ids)}
        for uri, decision_ids in sorted(cited.items())
    ]


__all__ = ["render_packet"]
