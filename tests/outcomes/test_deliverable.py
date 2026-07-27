"""Deliverable-kind DoD resolution: a cross-assigned task is judged by what it owes, not the role."""

from __future__ import annotations

from chorus.outcomes import DoDKind, Verifier
from chorus.outcomes._deliverable import (
    DeliverableKind,
    classify_deliverable,
    resolve_delivery_verifier,
)


class _Plugin:
    """Minimal stand-in for a RolePlugin: only ``dod_generator`` is read here."""

    def __init__(self, generator) -> None:
        self.dod_generator = generator


def _analyst_generator(intent: str) -> Verifier:
    # Mirrors the real analyst: every intent falls through to a findings review.
    return Verifier.agent_review(rubric="judge findings.md", artifact_class="finding")


def _frontend_generator(intent: str) -> Verifier:
    del intent  # the real frontend generator ignores intent and emits a code floor
    return Verifier.command("python -c 'pass'", artifact_class="pr")


def test_classify_catches_test_work() -> None:
    assert classify_deliverable("Add Playwright e2e tests for typing -> preview") is (
        DeliverableKind.TESTS
    )
    assert classify_deliverable("write unit tests with captured evidence") is DeliverableKind.TESTS


def test_in_craft_intent_uses_role_generator() -> None:
    # An analyst asked for analysis work keeps its own findings DoD.
    v = resolve_delivery_verifier("investigate the drop and write findings.md", _Plugin(_analyst_generator))
    assert v.artifact_class == "finding"


def test_ambiguous_intent_defers_to_role() -> None:
    assert classify_deliverable("handle the assigned work") is DeliverableKind.ROLE_DEFAULT
    v = resolve_delivery_verifier("handle the assigned work", _Plugin(_analyst_generator))
    assert v.artifact_class == "finding"  # the role default, unchanged


def test_analyst_assigned_tests_is_judged_as_tests_not_findings() -> None:
    # The live-run bug: analyst (native = findings) given a testing task must be judged as tests.
    v = resolve_delivery_verifier(
        "Add Playwright e2e tests and ensure evidence artifacts are captured",
        _Plugin(_analyst_generator),
    )
    assert v.kind is DoDKind.AGENT_REVIEW
    assert v.artifact_class == "tests"
    assert "findings.md" not in v.rubric()  # not the analyst's findings rubric


def test_frontend_assigned_tests_is_judged_as_tests_not_a_code_command() -> None:
    v = resolve_delivery_verifier("write the e2e test suite", _Plugin(_frontend_generator))
    assert v.artifact_class == "tests"


def test_frontend_assigned_code_keeps_its_own_command_floor() -> None:
    # In-craft: a code task on a code-native role stays with the role's command floor.
    v = resolve_delivery_verifier("implement the markdown editor component", _Plugin(_frontend_generator))
    assert v.kind is DoDKind.COMMAND
    assert v.artifact_class == "pr"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
