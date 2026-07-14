"""Typed Definition-of-Done verifiers (spec 04 §1).

The DoD is the cheapest *sufficient* verifier for an artifact class (B3.1). It
is generated at intake by the assignee's role plugin, persisted typed on
``task.dod``, and enforced by **dream's evaluator inside ``run_task``** — never a
self-report. Three tiers:

    Verifier(kind) = Command        # objective gate: a shell command exits 0
                   | AgentReview    # judgment gate: the built-in system verifier verdicts
                   | HumanApproval  # a person decides (the approval primitive)
                   | ReviewedBuild  # the system verifier discovers + judges; the kernel runs the command
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DoDKind(StrEnum):
    """Which verifier tier a :class:`Verifier` carries."""

    COMMAND = "command"
    AGENT_REVIEW = "agent_review"
    HUMAN_APPROVAL = "human_approval"
    REVIEWED_BUILD = "reviewed_build"


@dataclass(frozen=True)
class Command:
    """Objective gate — a shell command must exit 0 (tests/CI/typecheck)."""

    command: str
    timeout_s: int = 300


@dataclass(frozen=True)
class AgentReview:
    """Judgment gate — the built-in system verifier renders a verdict against a rubric."""

    reviewer_role: str = "reviewer"
    rubric: str = ""


@dataclass(frozen=True)
class HumanApproval:
    """A person decides — the approval primitive (spec 04 §5)."""

    approver: str = "board"


@dataclass(frozen=True)
class ReviewedBuild:
    """Reviewed build — language-agnostic, judgment-aware engineer gate (M3 reviewed-build).

    The read-only system verifier *discovers* the project's verify command and *judges* the diff; the
    kernel runs that command as the deterministic objective floor. The author's beat runs no hardcoded
    command (no language lock), and ``done`` means the discovered command exits 0 and verification
    approved the diff.
    """

    reviewer_role: str = "reviewer"
    rubric: str = ""
    verify_timeout_s: int = 600


# The DoD spec union (spec 04 §1).
DoDSpec = Command | AgentReview | HumanApproval | ReviewedBuild


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
    def human_approval(
        cls, *, approver: str = "board", artifact_class: str = "decision"
    ) -> Verifier:
        return cls(DoDKind.HUMAN_APPROVAL, HumanApproval(approver), artifact_class)

    @classmethod
    def reviewed_build(
        cls,
        *,
        reviewer_role: str = "reviewer",
        rubric: str = "",
        artifact_class: str = "pr",
        verify_timeout_s: int = 600,
    ) -> Verifier:
        return cls(
            DoDKind.REVIEWED_BUILD,
            ReviewedBuild(reviewer_role, rubric, verify_timeout_s),
            artifact_class,
        )

    def verification_steps(self) -> tuple[VerificationStep, ...]:
        """The objective checks dream's evaluator should run — the ``Command`` gate, else none.

        ``AgentReview``, ``HumanApproval``, and ``ReviewedBuild`` are chorus-orchestrated (a Reviewer
        beat / an approval / a reviewer-discovered command the kernel runs), not subprocesses dream runs
        at the worker's own beat, so they contribute no verification steps.
        """
        if isinstance(self.spec, Command):
            return (VerificationStep(command=self.spec.command, timeout_s=self.spec.timeout_s),)
        return ()

    def rubric(self) -> str:
        """The review rubric dream's evaluator judges the artefact against (spec 16).

        ``AgentReview`` and ``ReviewedBuild`` carry a rubric; folding it into the single in-beat
        evaluator turn (via dream ``run_task(rubric=...)``) is what collapses the redundant second
        Reviewer beat — one task, one ``run_task``, one verdict. ``Command``/``HumanApproval`` carry
        none.
        """
        if isinstance(self.spec, (AgentReview, ReviewedBuild)):
            return self.spec.rubric
        return ""


__all__ = [
    "AgentReview",
    "Command",
    "DoDKind",
    "DoDSpec",
    "HumanApproval",
    "ReviewedBuild",
    "VerificationStep",
    "Verifier",
]
