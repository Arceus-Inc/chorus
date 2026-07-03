"""Content-batch + swipe review — the "Tinder for marketing" primitive (spec GM §3; Result/Polsia).

A marketing beat rarely ships *one* asset: it drafts a *batch* of competing posts/reels/blogs, ranks
them offline (the branch tournament), then a human **swipes** accept/reject over the top before any
of them publish. This module is the role-agnostic data + pure function for that human step — it is
*not* the publish (a publish is a gated SEND through a :class:`~chorus.webplugins.WebPlugin`); it is
the fail-closed decision of *which* drafts earned the gate.

Pure and deterministic: feed it drafts and the accepted ids, get the accepted/rejected split back in
the order they were presented. Nothing publishes until something is accepted (fail-closed).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from chorus.webplugins._trust import PluginKind


@dataclass(frozen=True)
class Draft:
    """One generated marketing asset awaiting the swipe (a post/reel/blog/ad creative).

    ``channel`` is the :class:`~chorus.webplugins._trust.PluginKind` it would publish through (so the
    gate knows which capped channel a yes commits to); ``body`` is the asset itself.
    """

    id: str
    channel: PluginKind
    body: str


@dataclass(frozen=True)
class SwipeOutcome:
    """The result of a swipe review — the accepted drafts (to publish) and the rejected ones.

    ``accepted`` preserves the presented order so the publish loop ships them top-first; ``rejected``
    is the complement. ``accepted`` empty means nothing crossed the gate — the fail-closed default.
    """

    accepted: tuple[Draft, ...]
    rejected: tuple[Draft, ...]

    @property
    def any_accepted(self) -> bool:
        """True iff at least one draft earned the publish gate."""
        return bool(self.accepted)


def swipe_review(drafts: Iterable[Draft], *, accept: Iterable[str]) -> SwipeOutcome:
    """Split a draft batch into accepted/rejected by the human's swipe (spec GM §3, §9 gate).

    ``accept`` is the set of draft ids the human swiped right on; every other draft is rejected. The
    split preserves input order. Fail-closed: an empty ``accept`` publishes nothing. An ``accept`` id
    that matches no draft is ignored (a stale swipe can never conjure an asset to publish).
    """
    accepted_ids = set(accept)
    accepted: list[Draft] = []
    rejected: list[Draft] = []
    for draft in drafts:
        (accepted if draft.id in accepted_ids else rejected).append(draft)
    return SwipeOutcome(accepted=tuple(accepted), rejected=tuple(rejected))


__all__ = [
    "Draft",
    "SwipeOutcome",
    "swipe_review",
]
