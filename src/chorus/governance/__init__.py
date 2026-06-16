"""Approvals & governance gates (spec 04 §5).

A resolved ``approval`` performs an org mutation. Today the governed action is the **task gate** —
:class:`GovernanceResolver` opens one (parking the task ``blocked``) and resolves it (approve / deny)
into the task's outcome per its :class:`~chorus.ledger.ApprovalGate`. Budget-incident approvals are
resolved by the §3 enforcer; ``hire_employee`` / ``plan_approval`` ride later with spec 06.
"""

from __future__ import annotations

from chorus.governance._resolver import GovernanceError, GovernanceResolver, ResolveOutcome

__all__ = ["GovernanceError", "GovernanceResolver", "ResolveOutcome"]
