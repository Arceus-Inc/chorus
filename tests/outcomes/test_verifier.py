"""Typed DoD verifiers → the objective checks dream's evaluator runs (spec 04 §1)."""

from __future__ import annotations

import pytest

from chorus.outcomes import VerificationStep, Verifier

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
