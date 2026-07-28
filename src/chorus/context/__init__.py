"""Task context — the kernel's answer to "what does this beat need to know?".

One packet, projected from durable ledger rows and keyed by ``task_id``, replacing the ad-hoc
string concatenations that accreted at the harness boundary. See :mod:`chorus.context._packet` for
why the key matters.

chorus core owns this because it is a mechanism over the ledger: it must stay dream-free, so the
harness calls it rather than the other way round.
"""

from __future__ import annotations

from chorus.context._budget import (
    DEFAULT_BUDGET_TOKENS,
    SECTION_BUDGETS,
    SECTION_ORDER,
    estimate_tokens,
)
from chorus.context._flag import TCP_ENV_VAR, tcp_enabled
from chorus.context._packet import (
    DEFAULT_MAX_PRIOR_BEATS,
    PACKET_VERSION,
    SCOPE_GUARD,
    SUMMARY_CAP_CHARS,
    BudgetPosition,
    Contract,
    GoalLink,
    InboxItem,
    PeerWork,
    PriorBeat,
    TaskContextPacket,
)
from chorus.context._project import project_task_context
from chorus.context._render import ContextAudience, RenderedContext, render, sections_for

__all__ = [
    "DEFAULT_BUDGET_TOKENS",
    "DEFAULT_MAX_PRIOR_BEATS",
    "PACKET_VERSION",
    "SCOPE_GUARD",
    "SECTION_BUDGETS",
    "SECTION_ORDER",
    "SUMMARY_CAP_CHARS",
    "TCP_ENV_VAR",
    "BudgetPosition",
    "ContextAudience",
    "Contract",
    "GoalLink",
    "InboxItem",
    "PeerWork",
    "PriorBeat",
    "RenderedContext",
    "TaskContextPacket",
    "estimate_tokens",
    "project_task_context",
    "render",
    "sections_for",
    "tcp_enabled",
]
