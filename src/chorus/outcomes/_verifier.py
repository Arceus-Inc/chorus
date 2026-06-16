"""Typed Definition-of-Done verifiers (spec 04 §1).

The DoD is the cheapest *sufficient* verifier for an artifact class (B3.1). It
is generated at intake by the assignee's role plugin, persisted typed on
``task.dod``, and enforced by **dream's evaluator inside ``run_task``** — never a
self-report. Three tiers:

    Verifier(kind) = Command        # objective gate: a shell command exits 0
                   | AgentReview    # judgment gate: a Reviewer employee verdicts
                   | HumanApproval  # a person decides (the approval primitive)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DoDKind(StrEnum):
    """Which verifier tier a :class:`Verifier` carries."""

    COMMAND = "command"
    AGENT_REVIEW = "agent_review"
    HUMAN_APPROVAL = "human_approval"


@dataclass(frozen=True)
class Command:
    """Objective gate — a shell command must exit 0 (tests/CI/typecheck)."""

    command: str
    timeout_s: int = 300


@dataclass(frozen=True)
class AgentReview:
    """Judgment gate — a Reviewer-role employee renders a verdict against a rubric."""

    reviewer_role: str = "reviewer"
    rubric: str = ""


@dataclass(frozen=True)
class HumanApproval:
    """A person decides — the approval primitive (spec 04 §5)."""

    approver: str = "board"


# The DoD spec union (spec 04 §1).
DoDSpec = Command | AgentReview | HumanApproval


@dataclass(frozen=True)
class VerificationStep:
    """One objective check dream's evaluator runs as a real subprocess (the oracle, spec 15 P3).

    The chorus-side, dream-free shape of a verification step; the dream adapter renders it into
    dream's ``verification_steps`` at the call boundary.
    """

    command: str
    timeout_s: int = 300


@dataclass(frozen=True)
class Verifier:
    """The typed DoD persisted on ``task.dod`` and enforced by dream's evaluator.

    Mirrors the on-disk JSON shape ``{kind, spec, artifact_class}`` (spec 04 §1).
    Free-form checklists are banned — the evaluator can't rationalise a typed gate.
    """

    kind: DoDKind
    spec: DoDSpec
    artifact_class: str

    @classmethod
    def command(cls, command: str, *, artifact_class: str = "pr", timeout_s: int = 300) -> Verifier:
        return cls(DoDKind.COMMAND, Command(command, timeout_s), artifact_class)

    @classmethod
    def agent_review(
        cls, *, reviewer_role: str = "reviewer", rubric: str = "", artifact_class: str = "spec"
    ) -> Verifier:
        return cls(DoDKind.AGENT_REVIEW, AgentReview(reviewer_role, rubric), artifact_class)

    @classmethod
    def human_approval(cls, *, approver: str = "board", artifact_class: str = "decision") -> Verifier:
        return cls(DoDKind.HUMAN_APPROVAL, HumanApproval(approver), artifact_class)

    def verification_steps(self) -> tuple[VerificationStep, ...]:
        """The objective checks dream's evaluator should run — the ``Command`` gate, else none.

        ``AgentReview`` and ``HumanApproval`` are chorus-orchestrated (a Reviewer beat / an approval),
        not subprocesses dream runs, so they contribute no verification steps.
        """
        if isinstance(self.spec, Command):
            return (VerificationStep(command=self.spec.command, timeout_s=self.spec.timeout_s),)
        return ()


__all__ = [
    "AgentReview",
    "Command",
    "DoDKind",
    "DoDSpec",
    "HumanApproval",
    "VerificationStep",
    "Verifier",
]
