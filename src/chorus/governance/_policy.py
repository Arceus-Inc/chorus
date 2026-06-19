"""The governance policy — *when* a governed action needs a gate (§5 governance, Approach A).

A declarative, injected value (alongside ``Caps``), resolved **fail-closed**: an action is gated only
when the org has opted that action in. The empty default reproduces today's behaviour exactly — no
gates — so every existing run is unchanged until an org turns one on.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GovernancePolicy:
    """Which governed actions require human sign-off (spec 04 §5)."""

    require_hire_approval: bool = False
    plan_approval_roles: frozenset[str] = field(default_factory=frozenset)
    board_artifact_classes: frozenset[str] = field(default_factory=frozenset)

    def hire_gate_required(self) -> bool:
        """Whether hiring an employee needs approval before the employee is activated."""
        return self.require_hire_approval

    def plan_gate_required(self, manager_role: str) -> bool:
        """Whether a manager of ``manager_role`` needs its decomposed plan signed off."""
        return manager_role in self.plan_approval_roles

    def board_gate_required(self, artifact_class: str) -> bool:
        """Whether a landed artifact of ``artifact_class`` needs board approval to promote."""
        return artifact_class in self.board_artifact_classes


__all__ = ["GovernancePolicy"]
