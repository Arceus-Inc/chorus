"""Offline-eval outcome — a score-and-rank verifier, not boolean pass/fail (spec GM §3, §13).

chorus's existing decomposition fans out *to-do* work and verifies each child boolean (done / not).
A **branch tournament** instead fans out *competing* work: N variants are scored by an offline
backtest/holdout, ranked, and the top-k shipped. This module is the role-agnostic data + pure
function for that — no dream change, no live effect. The Engineer inherits the same primitive
(competing implementations), so it lives in the kernel, not the Growth Marketer plugin.

Pure and deterministic: feed it scored variants, get a ranked outcome and the gated top-k.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Variant:
    """One competing entry in a tournament — the thing being scored (a copy/audience/test variant)."""

    id: str
    description: str = ""


@dataclass(frozen=True)
class VariantScore:
    """An offline-eval result for one variant — a real number, not a boolean (spec GM §3).

    ``score`` is the ranking key (e.g. predicted lift); higher is better. ``metrics`` carries the
    supporting figures (power, sample size, CI) the backtest produced, for the report artifact.
    """

    variant_id: str
    score: float
    metrics: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class TournamentOutcome:
    """The ranked result of a branch tournament — ordered best-first, with the shipped top-k.

    ``ranked`` is every scored variant, descending by score (ties broken by ``variant_id`` for a
    stable, reproducible order). ``winners`` is the gated top-k the loop ships.
    """

    ranked: tuple[VariantScore, ...]
    top_k: int

    @property
    def winners(self) -> tuple[VariantScore, ...]:
        """The top-k variants the tournament ships (the gated, live-bound subset)."""
        return self.ranked[: self.top_k]

    @property
    def best(self) -> VariantScore | None:
        """The single highest-scoring variant, or ``None`` when the tournament had no entries."""
        return self.ranked[0] if self.ranked else None


def run_tournament(scores: Iterable[VariantScore], *, top_k: int = 1) -> TournamentOutcome:
    """Rank scored variants best-first and select the top-k (spec GM §3 branch tournament).

    A score-and-rank verifier: unlike a boolean gate it never "passes" a single variant — it orders
    the field and hands the loop the ``winners`` to ship. ``top_k`` is clamped to ``[0, n]`` so a
    caller can never ship more variants than competed.
    """
    if top_k < 0:
        raise ValueError(f"top_k must be non-negative, got {top_k}")
    # Descending by score; ``variant_id`` is the deterministic tie-breaker (ascending).
    ranked = tuple(sorted(scores, key=lambda s: (-s.score, s.variant_id)))
    return TournamentOutcome(ranked=ranked, top_k=min(top_k, len(ranked)))


__all__ = [
    "TournamentOutcome",
    "Variant",
    "VariantScore",
    "run_tournament",
]
