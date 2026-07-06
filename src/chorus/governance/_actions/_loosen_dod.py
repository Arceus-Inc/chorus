"""The loosen-DoD governed action (§1 DoD revisability over §5 governance).

Lowering a task's Definition-of-Done is staged (``dod.proposed_revision``) and gated: the task keeps
running under the **old, stricter** DoD until a human approves. Approve promotes the staged verifier to
in-force; deny / revise drop it. The subject is the task whose DoD is being loosened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chorus.governance._types import ActionOutcome
from chorus.ledger import Approval, ApprovalAction

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger

_LOOSENED = "loosened"
_UNCHANGED = "unchanged"
_WITHDRAWN = "withdrawn"


class LoosenDodAction:
    """The ``loosen_dod`` handler — promote, drop, or withdraw a staged DoD loosening."""

    action = ApprovalAction.LOOSEN_DOD

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def on_open(self, approval: Approval) -> None:
        return None  # the task keeps running under the old DoD; the resolver audits the GATED event

    def on_approve(self, approval: Approval) -> ActionOutcome:
        self._ledger.dod.apply_proposed_revision(
            approval.subject_id
        )  # swap + bump revision + clear
        return ActionOutcome(_LOOSENED)

    def on_deny(self, approval: Approval) -> ActionOutcome:
        self._ledger.dod.clear_proposed(approval.subject_id)  # keep the stricter DoD
        return ActionOutcome(_UNCHANGED)

    def on_revise(self, approval: Approval) -> ActionOutcome:
        self._ledger.dod.clear_proposed(approval.subject_id)  # withdraw the staged loosening
        return ActionOutcome(_WITHDRAWN)


__all__ = ["LoosenDodAction"]
