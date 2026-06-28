"""Web plugins — trust-scoped external reach + the offline-eval tournament (spec GM §5, §3).

Net-new and **role-agnostic** (spec GM §13): once built, the whole workforce inherits it. Two
kernel surfaces live here:

- the :class:`WebPlugin` integration layer — a registry of ``(name, kind, capability, auth ref,
  trust scope, spend cap)``, with read ungated and spend/send fail-closed behind a cap;
- the **branch tournament** / offline-eval outcome — a score-and-rank verifier (:func:`run_tournament`)
  that ranks N competing variants and selects the top-k, instead of a boolean pass/fail;
- the **content batch + swipe review** (:func:`swipe_review`) — the fail-closed human accept/reject
  over a batch of generated drafts before any of them publish ("Tinder for marketing");
- the **lead-search orchestration** skeleton (:func:`classify_query_health`, :func:`dedupe_leads`,
  :func:`exhaustiveness_stop`) — the deterministic control flow of signal-based prospecting.

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
from chorus.webplugins._search import (
    DedupeResult,
    Lead,
    LeadQuery,
    QueryHealth,
    QueryLevel,
    SearchPlatform,
    classify_query_health,
    dedupe_leads,
    exhaustiveness_stop,
    lead_dup_rate,
)
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
    "DedupeResult",
    "Draft",
    "Lead",
    "LeadQuery",
    "PluginKind",
    "QueryHealth",
    "QueryLevel",
    "RateCap",
    "SearchPlatform",
    "SpendCap",
    "SwipeOutcome",
    "TournamentOutcome",
    "Variant",
    "VariantScore",
    "WebPlugin",
    "WebPluginRegistry",
    "classify_query_health",
    "dedupe_leads",
    "exhaustiveness_stop",
    "is_secret_ref",
    "lead_dup_rate",
    "run_tournament",
    "swipe_review",
]
