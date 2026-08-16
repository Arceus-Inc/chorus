"""Typed outcome-capability check for manager assignment (BUG-006, spec 17).

A child whose declared :class:`~chorus.outcomes.OutcomeKind` the assignee's role cannot land is
refused before any ledger mutation. Undeclared outcomes skip the check so internal callers and
cross-craft work that relies on deliverable-kind DoD selection stay fail-open. Unknown/custom roles
also skip (fail open) rather than blocking legitimate plugin work.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from chorus.outcomes import OutcomeKind
from chorus.workforce import Employee


class _PlannedChild(Protocol):
    """The child fields the outcome check reads — satisfied by :class:`ChildPlan`."""

    @property
    def label(self) -> str: ...

    @property
    def assignee(self) -> str | None: ...

    @property
    def outcome_kind(self) -> OutcomeKind | None: ...


@dataclass(frozen=True)
class RoleOutcome:
    """What one known role lands — a typed catalog entry, not a domain dict."""

    role: str
    kind: OutcomeKind


@dataclass(frozen=True)
class OutcomeMismatch:
    """A child whose declared outcome the assignee's role cannot produce (fail-closed reason)."""

    label: str
    assignee: str
    role: str
    declared: OutcomeKind
    role_kind: OutcomeKind

    def refusal_clause(self) -> str:
        """One named mismatch for a tool refusal: assignee, role, declared vs produced kind."""
        return (
            f"{self.assignee} ({self.role} → {self.role_kind.value}) "
            f"for {self.declared.value} child {self.label!r}"
        )


# Canonical workforce + still-registered legacy roles. Mirrors each plugin's ``outcome_kind``.
_CANONICAL_ROLE_OUTCOMES: tuple[RoleOutcome, ...] = (
    RoleOutcome("backend_engineer", OutcomeKind.PR),
    RoleOutcome("frontend_engineer", OutcomeKind.PR),
    RoleOutcome("engineer", OutcomeKind.PR),
    RoleOutcome("pm", OutcomeKind.DOC),
    RoleOutcome("analyst", OutcomeKind.FINDING),
    RoleOutcome("manager", OutcomeKind.SUBTREE),
    RoleOutcome("reviewer", OutcomeKind.VERDICT),
    RoleOutcome("designer", OutcomeKind.DESIGN),
    RoleOutcome("marketer", OutcomeKind.CONTENT),
    RoleOutcome("ceo", OutcomeKind.DIRECTIVE),
)


@dataclass(frozen=True)
class RoleOutcomeCatalog:
    """Lookup of the deliverable each known role can produce."""

    entries: tuple[RoleOutcome, ...] = _CANONICAL_ROLE_OUTCOMES

    def kind_for(self, role: str) -> OutcomeKind | None:
        """The outcome ``role`` lands, or ``None`` when the role is unknown (fail open)."""
        for entry in self.entries:
            if entry.role == role:
                return entry.kind
        return None


def outcome_mismatches(
    children: Iterable[_PlannedChild],
    *,
    employees: Sequence[Employee],
    catalog: RoleOutcomeCatalog | None = None,
) -> tuple[OutcomeMismatch, ...]:
    """Children whose declared outcome their assignee's role cannot produce.

    Children with no declared outcome, no assignee, an unknown assignee, or a role outside the
    catalog are skipped (handled elsewhere / fail open).
    """
    index = catalog if catalog is not None else RoleOutcomeCatalog()
    by_id = {employee.id: employee for employee in employees}
    mismatches: list[OutcomeMismatch] = []
    for child in children:
        if child.outcome_kind is None or child.assignee is None:
            continue
        employee = by_id.get(child.assignee)
        if employee is None:
            continue
        role_kind = index.kind_for(employee.role)
        if role_kind is None or role_kind is child.outcome_kind:
            continue
        mismatches.append(
            OutcomeMismatch(
                label=child.label,
                assignee=child.assignee,
                role=employee.role,
                declared=child.outcome_kind,
                role_kind=role_kind,
            )
        )
    return tuple(mismatches)


__all__ = [
    "OutcomeMismatch",
    "RoleOutcome",
    "RoleOutcomeCatalog",
    "outcome_mismatches",
]
