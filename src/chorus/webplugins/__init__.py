"""Web plugins — trust-scoped external reach + the offline-eval tournament (spec GM §5, §3).

Net-new and **role-agnostic** (spec GM §13): once built, the whole workforce inherits it. Two
kernel surfaces live here:

- the :class:`WebPlugin` integration layer — a registry of ``(name, kind, capability, auth ref,
  trust scope, spend cap)``, with read ungated and spend/send fail-closed behind a cap;
- the **branch tournament** / offline-eval outcome — a score-and-rank verifier (:func:`run_tournament`)
  that ranks N competing variants and selects the top-k, instead of a boolean pass/fail;
- the **content batch + swipe review** (:func:`swipe_review`) — the fail-closed human accept/reject
  over a batch of generated drafts before any of them publish ("Tinder for marketing").

All reuse chorus's existing fail-closed trust + budget ideas; none touch dream.
"""

from __future__ import annotations

from chorus.webplugins._content import Draft, SwipeOutcome, swipe_review
from chorus.webplugins._outcome import (
    TournamentOutcome,
    Variant,
    VariantScore,
    run_tournament,
)
from chorus.webplugins._registry import WebPlugin, WebPluginRegistry
from chorus.webplugins._trust import (
    REF_PREFIX,
    Capability,
    PluginKind,
    RateCap,
    SpendCap,
    is_secret_ref,
)

__all__ = [
    "REF_PREFIX",
    "Capability",
    "Draft",
    "PluginKind",
    "RateCap",
    "SpendCap",
    "SwipeOutcome",
    "TournamentOutcome",
    "Variant",
    "VariantScore",
    "WebPlugin",
    "WebPluginRegistry",
    "is_secret_ref",
    "run_tournament",
    "swipe_review",
]
