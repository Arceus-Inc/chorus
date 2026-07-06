"""Each role's DoD generator returns the archetype its outcome needs (spec 04 §1).

Covers the full archetype surface across the default workforce: ReviewedBuild (engineer),
HumanApproval (reviewer), AgentReview (manager / analyst). The objective Command archetype is
exercised live (examples/analyst_live_command_dod.py) and at the verifier/enforcement level
(tests/outcomes/test_verifier.py, tests/heartbeat/test_dod_enforcement.py).
"""

from __future__ import annotations

import pytest

from chorus.outcomes import DoDKind, Verifier
from chorus_employee.analyst import analyst_plugin
from chorus_employee.engineer import engineer_plugin
from chorus_employee.manager import manager_plugin
from chorus_employee.reviewer import reviewer_plugin

pytestmark = pytest.mark.unit

_INTENT = "do the thing the task asks for"


def test_each_role_dod_returns_the_expected_archetype() -> None:
    cases = {
        "engineer": (engineer_plugin, DoDKind.REVIEWED_BUILD),
        "reviewer": (reviewer_plugin, DoDKind.HUMAN_APPROVAL),
        "manager": (manager_plugin, DoDKind.AGENT_REVIEW),
        "analyst": (analyst_plugin, DoDKind.AGENT_REVIEW),
    }
    for role, (plugin_fn, kind) in cases.items():
        verifier = plugin_fn().dod_generator(_INTENT)
        assert isinstance(verifier, Verifier), f"{role} dod must be a typed Verifier"
        assert verifier.kind is kind, f"{role} expected {kind}, got {verifier.kind}"


def test_agent_review_carries_a_rubric_no_command() -> None:
    v = analyst_plugin().dod_generator(_INTENT)
    assert v.rubric()  # the evaluator judges against it
    assert v.verification_steps() == ()  # no objective shell gate


def test_reviewed_build_carries_a_rubric() -> None:
    v = engineer_plugin().dod_generator(_INTENT)
    assert v.kind is DoDKind.REVIEWED_BUILD
    assert v.rubric()


def test_human_approval_has_no_rubric_or_command() -> None:
    v = reviewer_plugin().dod_generator(_INTENT)
    assert v.kind is DoDKind.HUMAN_APPROVAL
    assert v.rubric() == "" and v.verification_steps() == ()


def test_command_archetype_runs_an_objective_gate() -> None:
    """The Command archetype (a human may set it via `dod set`) is the objective oracle."""
    v = Verifier.command('python -c "import sys; sys.exit(0)"', artifact_class="finding")
    assert v.kind is DoDKind.COMMAND
    steps = v.verification_steps()
    assert len(steps) == 1 and "python" in steps[0].command
    assert v.rubric() == ""  # objective gate, no judgment rubric
