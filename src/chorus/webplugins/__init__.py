"""Web plugins — trust-scoped external reach + the offline-eval tournament (spec GM §5, §3).

Net-new and **role-agnostic** (spec GM §13): once built, the whole workforce inherits it. Two
kernel surfaces live here:

- the :class:`WebPlugin` integration layer — a registry of ``(name, kind, capability, auth ref,
  trust scope, spend cap)``, with read ungated and spend/send fail-closed behind a cap;
- the **branch tournament** / offline-eval outcome — a score-and-rank verifier (:func:`run_tournament`)
  that ranks N competing variants and selects the top-k, instead of a boolean pass/fail.

Both reuse chorus's existing fail-closed trust + budget ideas; neither touches dream.
"""

from __future__ import annotations

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
    SpendCap,
    is_secret_ref,
)

__all__ = [
    "REF_PREFIX",
    "Capability",
    "PluginKind",
    "SpendCap",
    "TournamentOutcome",
    "Variant",
    "VariantScore",
    "WebPlugin",
    "WebPluginRegistry",
    "is_secret_ref",
    "run_tournament",
]
