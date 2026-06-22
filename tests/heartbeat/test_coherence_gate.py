"""The coherence DoD is a Command the kernel's integrate floor runs (spec 15 §4.3).

The manager's integrate is gated on coherence by giving the goal a ``Verifier.command`` DoD; the
existing ``_integrate_floor_verdict`` runs that command in the integrator's worktree (company main) once
the subtree is terminal, and parks the goal ``blocked`` on a non-zero exit (covered by the adaptive-loop
tests in ``test_m3_park_integrate.py``). This test locks the DoD shape the wiring depends on.
"""

from __future__ import annotations

import pytest

from chorus.outcomes import Verifier

pytestmark = pytest.mark.unit


def test_coherence_dod_is_a_single_command_step() -> None:
    verifier = Verifier.command("python -m chorus.coherence", artifact_class="subtree")
    steps = verifier.verification_steps()
    assert len(steps) == 1
    assert steps[0].command == "python -m chorus.coherence"


def test_coherence_dod_carries_no_rubric() -> None:
    # a Command DoD is a pure objective gate — no reviewer rubric to rationalise around.
    assert Verifier.command("python -m chorus.coherence").rubric() == ""
