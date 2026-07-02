"""The Analyst's WebPlugin grants — trust-scoped external reach, secret-bound (spec GM §5, reused).

The Analyst's reach is deliberately *read-only*: it pulls from the analytic warehouse and researches
the open web, and does neither by holding a raw credential nor by touching a live system. Both grants
are :class:`~chorus.webplugins.Capability.READ` — cheap, reversible, ungated — so the Analyst never
carries a :class:`~chorus.webplugins.SpendCap`/:class:`~chorus.webplugins.RateCap`; it has no send or
spend to bound. Auth is always a secret *ref* (``ref:warehouse_ro``), never an inline value, so the
same fail-closed boundary the Growth Marketer's gated plugins sit behind also frames the Analyst's
harmless reads. ``subagent_grants`` records which Tier-1 specialist may reach which plugin — the
one auditable seam: only the data/modeling/critic trio touch the warehouse, and only the scout
touches the web.

This reuses Divyansh's role-agnostic :mod:`chorus.webplugins` layer verbatim (spec GM §13: once the
kernel ships the WebPlugin registry, the whole workforce inherits it). The live web tools the Analyst
actually calls are dream's built-in ``web_search``/``web_extract`` (registered in its harness); this
module is the *governance* declaration of that reach — what it may touch, under which secret ref, at
which capability — the same table the Growth Marketer publishes for her nine integrations.
"""

from __future__ import annotations

from chorus.webplugins import (
    Capability,
    PluginKind,
    WebPlugin,
    WebPluginRegistry,
)

# The Analyst's two read integrations — both ungated (READ), both secret-ref bound (spec GM §5).
WAREHOUSE = WebPlugin(
    name="warehouse",
    kind=PluginKind.WAREHOUSE,
    capability=Capability.READ,
    auth_ref="ref:warehouse_ro",
    scope="read-only, row/role-scoped analytic views (warehouse_query)",
)
WEB = WebPlugin(
    name="web",
    kind=PluginKind.SEARCH,
    capability=Capability.READ,
    auth_ref="ref:tavily",
    scope="read-only web research — search then extract a source in full (web_search / web_extract)",
)

_PLUGINS: tuple[WebPlugin, ...] = (WAREHOUSE, WEB)

# Which Tier-1 specialist may reach which plugin (spec GM §4/§5). The data/modeling/critic trio read
# the warehouse; the scout reads the web; the narrative writer touches neither (it drafts from
# already-computed local outputs). Both grants are READ, so there is no gated seam to audit here —
# only the shape of who reaches what.
_GRANTS: dict[str, tuple[str, ...]] = {
    "data": ("warehouse",),
    "modeling": ("warehouse",),
    "critic": ("warehouse",),
    "scout": ("web",),
}


def analyst_webplugins() -> WebPluginRegistry:
    """The registry of the Analyst's trust-scoped read integrations (spec GM §5, reused)."""
    return WebPluginRegistry.from_plugins(_PLUGINS)


def subagent_grants() -> dict[str, tuple[str, ...]]:
    """Map each Tier-1 specialist to the WebPlugin names it is granted (spec GM §4/§5)."""
    return dict(_GRANTS)


__all__ = [
    "WAREHOUSE",
    "WEB",
    "analyst_webplugins",
    "subagent_grants",
]
