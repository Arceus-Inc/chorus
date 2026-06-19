"""Typed DoD verifiers → the objective checks dream's evaluator runs (spec 04 §1)."""

from __future__ import annotations

import pytest

from chorus.outcomes import DoDKind, ReviewedBuild, VerificationStep, Verifier

pytestmark = pytest.mark.unit


def test_command_verifier_yields_a_verification_step() -> None:
    steps = Verifier.command("pytest -q && ruff check .").verification_steps()
    assert steps == (VerificationStep(command="pytest -q && ruff check ."),)


def test_command_step_carries_the_timeout() -> None:
    steps = Verifier.command("pytest -q", timeout_s=120).verification_steps()
    assert steps == (VerificationStep(command="pytest -q", timeout_s=120),)


def test_agent_review_yields_no_objective_steps() -> None:
    assert Verifier.agent_review().verification_steps() == ()


def test_human_approval_yields_no_objective_steps() -> None:
    assert Verifier.human_approval().verification_steps() == ()


def test_reviewed_build_is_a_reviewer_gate_with_no_self_run_step() -> None:
    # A reviewed build is reviewer-orchestrated (the reviewer discovers the command, the kernel runs it),
    # so the engineer's OWN beat runs no objective step — the gate is review + kernel-run.
    verifier = Verifier.reviewed_build(rubric="meets intent, clean diff")
    assert verifier.kind is DoDKind.REVIEWED_BUILD
    assert verifier.artifact_class == "pr"
    assert isinstance(verifier.spec, ReviewedBuild)
    assert verifier.spec.reviewer_role == "reviewer" and verifier.spec.rubric == "meets intent, clean diff"
    assert verifier.verification_steps() == ()


def test_reviewed_build_carries_a_verify_timeout() -> None:
    verifier = Verifier.reviewed_build(verify_timeout_s=900)
    assert isinstance(verifier.spec, ReviewedBuild) and verifier.spec.verify_timeout_s == 900
