"""Approvals & governance gates (spec 04 §5) — the generalized governed-action queue (Approach A).

A resolved ``approval`` performs an org mutation. :class:`GovernanceResolver` is a thin, atomic,
audited dispatcher: it opens a gate (parking/flagging its subject) and resolves it (approve / deny /
request-revision) by delegating to the :class:`GovernedAction` handler registered for the approval's
:class:`~chorus.ledger.ApprovalAction`. The task gate is one such handler; ``hire_employee`` /
``plan_approval`` / ``board_approval`` ride later slices. Budget-incident approvals stay with the §3
enforcer.
"""

from __future__ import annotations

from chorus.governance._registry import (
    GovernanceRegistry,
    UnregisteredAction,
    default_actions,
)
from chorus.governance._resolver import GovernanceError, GovernanceResolver, ResolveOutcome
from chorus.governance._types import ActionOutcome, ApprovalDecision, GovernedAction

__all__ = [
    "ActionOutcome",
    "ApprovalDecision",
    "GovernanceError",
    "GovernanceRegistry",
    "GovernanceResolver",
    "GovernedAction",
    "ResolveOutcome",
    "UnregisteredAction",
    "default_actions",
]
