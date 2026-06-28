"""The Growth Marketer's WebPlugin grants — trust-scoped external reach, secret-bound (spec GM §5).

Mira's integrations are the §5 table made concrete: read plugins (warehouse, analytics, brand DAM)
are cheap and ungated; write-design (experimentation) creates drafts only; the gated plugins reach the
human gate and carry a cap — a :class:`~chorus.webplugins.SpendCap` where the blast radius is dollars
(ad spend) or a :class:`~chorus.webplugins.RateCap` where it is frequency (an email list 2 sends/day,
a Twitter/X account 1 post/day, per Result/Polsia channel limits). Auth is always a secret *ref*
(``ref:warehouse_ro``), never an inline value. ``subagent_grants`` records which Tier-1 specialist may
reach which plugin — the blast-radius surface is one small, auditable seam: only Channel touches a
write/spend/send plugin.
"""

from __future__ import annotations

from chorus.webplugins import (
    Capability,
    PluginKind,
    RateCap,
    SpendCap,
    WebPlugin,
    WebPluginRegistry,
)

# The category integrations (vendors are placeholders for categories — spec GM §5, assumption 4).
WAREHOUSE = WebPlugin(
    name="warehouse",
    kind=PluginKind.WAREHOUSE,
    capability=Capability.READ,
    auth_ref="ref:warehouse_ro",
    scope="read-only, row/role-scoped views",
)
ANALYTICS = WebPlugin(
    name="analytics",
    kind=PluginKind.ANALYTICS,
    capability=Capability.READ,
    auth_ref="ref:analytics_ro",
    scope="read-only event & funnel API",
)
EXPERIMENTATION = WebPlugin(
    name="experimentation",
    kind=PluginKind.EXPERIMENTATION,
    capability=Capability.WRITE_DESIGN,
    auth_ref="ref:statsig",
    scope="create draft tests + read results; cannot start live",
)
CRM = WebPlugin(
    name="crm",
    kind=PluginKind.EMAIL_CRM,
    capability=Capability.SEND,
    auth_ref="ref:crm",
    scope="scoped audience; live send → HumanApproval",
    rate_cap=RateCap(per_day=2),  # frequency-capped, not dollar-capped (a send spends no money)
)
SOCIAL = WebPlugin(
    name="social",
    kind=PluginKind.SOCIAL,
    capability=Capability.SEND,
    auth_ref="ref:social",
    scope="organic post publishing; swipe-approved → HumanApproval",
    rate_cap=RateCap(per_day=1),  # one post/day, like the Result/Polsia shared X account
)
ADS = WebPlugin(
    name="ads",
    kind=PluginKind.ADS,
    capability=Capability.SPEND,
    auth_ref="ref:ads",
    scope="budget-capped; spend → gate 2 + approval",
    spend_cap=SpendCap(per_action_cents=500_00, daily_cents=2_000_00),
)
DAM = WebPlugin(
    name="dam",
    kind=PluginKind.CREATIVE_DAM,
    capability=Capability.READ,
    auth_ref="ref:dam_ro",
    scope="read-only asset + guideline fetch",
)

_PLUGINS: tuple[WebPlugin, ...] = (WAREHOUSE, ANALYTICS, EXPERIMENTATION, CRM, SOCIAL, ADS, DAM)

# Which Tier-1 specialist may reach which plugin (spec GM §4/§5). Only Channel holds a gated plugin —
# the one small, auditable write/spend seam.
_GRANTS: dict[str, tuple[str, ...]] = {
    "segment": ("warehouse", "analytics"),
    "creative": ("dam",),
    "experiment": ("warehouse", "experimentation"),
    "channel": ("crm", "social", "ads"),
    "monitor": ("analytics", "experimentation"),
}


def growth_marketer_webplugins() -> WebPluginRegistry:
    """The registry of Mira's trust-scoped integrations (spec GM §5)."""
    return WebPluginRegistry.from_plugins(_PLUGINS)


def subagent_grants() -> dict[str, tuple[str, ...]]:
    """Map each Tier-1 specialist to the WebPlugin names it is granted (spec GM §4/§5)."""
    return dict(_GRANTS)


__all__ = [
    "ADS",
    "ANALYTICS",
    "CRM",
    "DAM",
    "EXPERIMENTATION",
    "SOCIAL",
    "WAREHOUSE",
    "growth_marketer_webplugins",
    "subagent_grants",
]
