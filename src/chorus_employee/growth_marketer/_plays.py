"""Play recommender — ranking the *angles* by which Mira scales the business (spec GM §3; Polsia).

A **play** is a repeatable go-to-market scenario: "founders who just raised a Series A and are
building out the team", "companies whose CTO just stepped down". Each play implies an ideal customer
and a set of observable *signals* a prospect leaves when they enter it. Mira's job at the top of the
funnel is to pick *which* plays to run — there are always more angles than capacity, so the plays
compete and the best-yielding ones win.

This module is the role-specific data + recommender for that. It deliberately **reuses the kernel
branch tournament** (:func:`~chorus.webplugins.run_tournament`): a scored play is just a competing
variant, so ranking plays is the same score-and-rank primitive that ranks subject lines — no new
machinery. Expanding a chosen play into platform queries and harvesting leads is *judgment + I/O*
(the :data:`~chorus.swarm.LEAD_ORCHESTRATOR` swarm agent); this module only chooses the angle.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from chorus.webplugins import SearchPlatform, VariantScore, run_tournament


@dataclass(frozen=True)
class Play:
    """A go-to-market angle — a buying scenario plus the customer it implies (spec GM §3).

    ``context`` is the scenario ("just raised a Series A, building out the team"); ``icp`` is who that
    points at; ``signal`` is the observable footprint a prospect in this play leaves (the thing the
    search strategies hunt for). ``id`` is stable so a play can be ranked and referenced downstream.
    """

    id: str
    title: str
    icp: str
    context: str
    signal: str = ""


@dataclass(frozen=True)
class SearchStrategy:
    """One angled way to find a play's leads on one platform (spec GM §3; query-optimizer strategy).

    ``concept`` is *why* this signal proves intent; ``sample_query`` is the boolean exemplar the
    orchestrator expands into the broad/intent/icp grid. ``platform`` is where the footprint lives.
    """

    title: str
    concept: str
    sample_query: str
    platform: SearchPlatform


@dataclass(frozen=True)
class ScoredPlay:
    """A play with its expected yield — the ranking key for the recommender (spec GM §3).

    ``score`` blends fit and expected return (e.g. ICP-match x reachable volume x intent freshness);
    higher is better. ``metrics`` carries the supporting figures for the playbook artifact.
    """

    play: Play
    score: float
    metrics: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PlaybookRecommendation:
    """The ranked plays and the gated top-k Mira actually runs this cycle (spec GM §3)."""

    ranked: tuple[Play, ...]
    winners: tuple[Play, ...]

    @property
    def top(self) -> Play | None:
        """The single best-yielding play, or ``None`` when nothing was scored."""
        return self.ranked[0] if self.ranked else None


def recommend_plays(scored: Iterable[ScoredPlay], *, top_k: int = 3) -> PlaybookRecommendation:
    """Rank candidate plays best-first and select the top-k to run (spec GM §3 branch tournament).

    Genuinely delegates to :func:`~chorus.webplugins.run_tournament` — each scored play becomes a
    competing variant, the tournament orders them with the same deterministic score-then-id tie-break,
    and the ``top_k`` it ships are the plays Mira runs. Raises ``ValueError`` if two plays share an id
    (an ambiguous ranking key would make the winners unresolvable).
    """
    by_id: dict[str, Play] = {}
    variant_scores: list[VariantScore] = []
    for sp in scored:
        if sp.play.id in by_id:
            raise ValueError(f"duplicate play id {sp.play.id!r} — play ids must be unique to rank")
        by_id[sp.play.id] = sp.play
        variant_scores.append(VariantScore(sp.play.id, sp.score, sp.metrics))
    outcome = run_tournament(variant_scores, top_k=top_k)
    ranked = tuple(by_id[s.variant_id] for s in outcome.ranked)
    winners = tuple(by_id[s.variant_id] for s in outcome.winners)
    return PlaybookRecommendation(ranked=ranked, winners=winners)


__all__ = [
    "Play",
    "PlaybookRecommendation",
    "ScoredPlay",
    "SearchStrategy",
    "recommend_plays",
]
