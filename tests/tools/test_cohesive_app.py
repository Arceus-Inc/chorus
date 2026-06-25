"""Cohesive app classifier guards for manager decomposition."""

from __future__ import annotations

from chorus.lifecycle import ChildPlan
from chorus_tools._cohesive_app import looks_like_cohesive_app, looks_like_sidecar_child


def test_complete_full_stack_repo_with_single_root_gate_is_cohesive() -> None:
    assert looks_like_cohesive_app(
        "Deliver the complete Boardsync full-stack repo as ONE runnable application: Node backend "
        "with WebSocket real-time collaboration; React frontend; typed shared schema. Implement a "
        "single root package-manager gate command that builds and runs proof tests from a clean checkout."
    )


def test_proof_tests_are_sidecar_work_for_a_cohesive_app() -> None:
    assert looks_like_sidecar_child(
        ChildPlan(
            label="proof-tests",
            intent="implement headless automated proof tests for broadcast and reconnect replay",
            assignee="di",
        ),
        "engineer",
    )