"""Decision OS row models — an immutable decision and the claims that ground it (pm design doc §10).

A PM ships a *decision*, not a doc: :class:`DecisionRecord` is the ADR-style bet — the option chosen,
its rationale, a self-assessed confidence, the rejected alternatives, the outcome metric, and a
**revisit trigger** ("if the metric doesn't move within window W, reopen"). It is immutable once
created; a change supersedes it with a new id (``superseded_by`` points forward). Each
:class:`Claim` links the decision back to one cited source — the claims ledger that makes the
recommendation *checkable* (faithfulness), the raw material the Researcher already produces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RejectedAlternative:
    """One option the decision considered and rejected, with the reason it lost.

    Example: ``RejectedAlternative(option="second LLM provider", reason="provider outages are rare")``.
    """

    option: str
    reason: str


@dataclass(frozen=True)
class DecisionRecord:
    """An immutable, ADR-style product decision (pm design doc §10).

    Immutable once created: a change never edits a record, it creates a successor and points this
    row's ``superseded_by`` at it. ``confidence`` is the PM's self-assessment in ``0..1``; the
    grounding-floor DoD and ``CapabilityService.record_decision`` enforce the policy that a low
    confidence must be backed by cited claims.
    """

    id: str
    task_id: str
    option: str
    rationale: str
    confidence: float
    outcome_metric: str
    revisit_trigger: str
    rejected_alternatives: tuple[RejectedAlternative, ...] = ()
    superseded_by: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class Claim:
    """One cited fact a decision rests on — a row in the claims ledger (pm design doc §10).

    ``source_url`` is the citation the PM surfaces in its plan; ``confidence`` is how strongly the
    source supports the claim in ``0..1``.
    """

    id: str
    decision_id: str
    text: str
    source_url: str
    confidence: float
    created_at: datetime | None = None


__all__ = ["Claim", "DecisionRecord", "RejectedAlternative"]
