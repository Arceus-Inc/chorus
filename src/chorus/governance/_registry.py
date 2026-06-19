"""The governed-action registry — action → handler, fail-closed (§5 governance, Approach A).

Mirrors :class:`~chorus.outcomes.LanderRegistry` / :class:`~chorus.roles.RoleRegistry`: a frozen map
from :class:`ApprovalAction` to its one :class:`GovernedAction` handler. ``get`` on an unregistered
action raises rather than guessing, so a gate whose action has no handler fails loudly.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from chorus.governance._actions import (
    BoardApprovalAction,
    HireEmployeeAction,
    LoosenDodAction,
    PlanApprovalAction,
    TaskGateAction,
)
from chorus.governance._errors import GovernanceError
from chorus.governance._types import GovernedAction
from chorus.ledger import ApprovalAction

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger


class UnregisteredAction(GovernanceError):
    """No handler is registered for an :class:`ApprovalAction` (fail-closed)."""


class GovernanceRegistry:
    """An immutable ``ApprovalAction`` → :class:`GovernedAction` map."""

    def __init__(self, by_action: dict[ApprovalAction, GovernedAction]) -> None:
        self._by_action = dict(by_action)

    @classmethod
    def from_actions(cls, actions: Iterable[GovernedAction]) -> GovernanceRegistry:
        """Build a registry, rejecting a duplicate handler for the same action (fail-closed)."""
        by_action: dict[ApprovalAction, GovernedAction] = {}
        for handler in actions:
            if handler.action in by_action:
                raise ValueError(f"duplicate governed-action handler for {handler.action.value!r}")
            by_action[handler.action] = handler
        return cls(by_action)

    def get(self, action: ApprovalAction) -> GovernedAction:
        try:
            return self._by_action[action]
        except KeyError as exc:
            raise UnregisteredAction(
                f"no governed-action handler registered for {action.value!r}"
            ) from exc


def default_actions(ledger: SqliteLedger) -> list[GovernedAction]:
    """The built-in governed actions, bound to ``ledger`` (extended one handler per slice)."""
    return [
        TaskGateAction(ledger),
        HireEmployeeAction(ledger),
        PlanApprovalAction(ledger),
        BoardApprovalAction(ledger),
        LoosenDodAction(ledger),
    ]


__all__ = ["GovernanceRegistry", "UnregisteredAction", "default_actions"]
