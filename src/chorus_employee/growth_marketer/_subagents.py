"""Mira's Tier-1 specialist subagents — the swarm she dispatches (spec GM §4).

Two tiers compose under Mira. *Tier-1 role specialists* are domain-specific and defined here in her
plugin; they own the growth logic and run as dream's bounded, ephemeral intra-task swarm. They in
turn spawn *Tier-2* shared capability agents (the :data:`~chorus.swarm.QUERY_ORCHESTRATOR`) for
reusable reasoning. Each specialist is a **capability-minimized overlay** (narrower-wins): it only
drops tools / tightens reach, never widens, so authority is monotonic — no specialist can escalate
past Mira's manifest. Only :data:`CHANNEL` touches a write/spend plugin, so the blast-radius surface
is one small, auditable seam.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GrowthSubagent:
    """One Tier-1 specialist overlay — domain reasoning + the WebPlugins/swarm roles it pulls in.

    ``webplugins`` are the trust-scoped integrations it is granted (see :mod:`._integrations`);
    ``spawns`` are the shared Tier-2 swarm roles it delegates reusable reasoning to.
    """

    name: str
    description: str
    webplugins: tuple[str, ...] = ()
    spawns: tuple[str, ...] = field(default_factory=tuple)

    @property
    def writes(self) -> bool:
        """Whether this specialist holds any write/spend reach — true only for Channel (spec GM §4)."""
        return bool(self.webplugins) and self.name == "channel"


PROSPECTOR = GrowthSubagent(
    name="prospector",
    description=(
        "Scales the top of the funnel: ranks the go-to-market plays, then runs the lead sweep — "
        "expands each play into angled Google/LinkedIn/X/Reddit queries, reads each query's health, "
        "heals the bad ones, and harvests + dedupes real buyer leads. Read-only discovery; the actual "
        "outreach send is handed to Channel behind the gate."
    ),
    webplugins=("search",),
    spawns=("lead_orchestrator",),
)
SEGMENT = GrowthSubagent(
    name="segment",
    description=(
        "Pulls the cohort that moved, sizes the addressable audience, computes funnel drop-off; "
        "defines who each variant targets."
    ),
    webplugins=("warehouse", "analytics"),
    spawns=("query_orchestrator",),
)
CREATIVE = GrowthSubagent(
    name="creative",
    description=(
        "Drafts the variant content — subject lines, CTAs, ad copy, onboarding microcopy — on-brand, "
        "pulling voice from memory. No external write reach."
    ),
    webplugins=("dam",),
)
EXPERIMENT = GrowthSubagent(
    name="experiment",
    description=(
        "Designs the variant matrix, runs the offline back-test/holdout, checks sample-size/power, "
        "and ranks variants by predicted lift; owns the offline-eval outcome."
    ),
    webplugins=("warehouse", "experimentation"),
    spawns=("query_orchestrator",),
)
CHANNEL = GrowthSubagent(
    name="channel",
    description=(
        "The only specialist that spends/sends: publishes the swipe-approved content (organic posts, "
        "email sends), reaches out 1:1 to the prospector's approved leads, and pushes the winning "
        "top-k live — schedules the send, launches the ad set, allocates budget — every action "
        "fail-closed behind a gate and inside its channel cap."
    ),
    webplugins=("crm", "social", "ads", "outreach"),
)
MONITOR = GrowthSubagent(
    name="monitor",
    description=(
        "Watches the live metric post-launch, calls early-stop on losers, detects regressions, runs "
        "the daily channel-performance read and proposes budget reallocation (Channel executes it "
        "behind the gate), and emits the next loop's signal as a wake; closes the loop."
    ),
    webplugins=("analytics", "experimentation"),
    spawns=("query_orchestrator",),
)

GROWTH_SUBAGENTS: tuple[GrowthSubagent, ...] = (
    PROSPECTOR,
    SEGMENT,
    CREATIVE,
    EXPERIMENT,
    CHANNEL,
    MONITOR,
)


__all__ = [
    "CHANNEL",
    "CREATIVE",
    "EXPERIMENT",
    "GROWTH_SUBAGENTS",
    "MONITOR",
    "PROSPECTOR",
    "SEGMENT",
    "GrowthSubagent",
]
