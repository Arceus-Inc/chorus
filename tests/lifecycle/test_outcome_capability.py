"""Typed outcome-capability catalog — assignment refuses a declared kind the role cannot land."""

from __future__ import annotations

from chorus.lifecycle._capability import ChildPlan
from chorus.lifecycle._outcome_capability import (
    RoleOutcomeCatalog,
    outcome_mismatches,
)
from chorus.outcomes import OutcomeKind
from chorus.workforce import Employee


def test_declared_pr_to_pm_is_a_typed_mismatch() -> None:
    pam = Employee(id="pam", name="Pam", role="pm")
    mismatches = outcome_mismatches(
        (
            ChildPlan(
                label="impl",
                intent="build it",
                assignee="pam",
                outcome_kind=OutcomeKind.PR,
            ),
        ),
        employees=(pam,),
    )
    assert len(mismatches) == 1
    mismatch = mismatches[0]
    assert mismatch.assignee == "pam"
    assert mismatch.role == "pm"
    assert mismatch.declared is OutcomeKind.PR
    assert mismatch.role_kind is OutcomeKind.DOC


def test_matching_doc_for_pm_is_not_a_mismatch() -> None:
    pam = Employee(id="pam", name="Pam", role="pm")
    mismatches = outcome_mismatches(
        (
            ChildPlan(
                label="spec",
                intent="write the api spec",
                assignee="pam",
                outcome_kind=OutcomeKind.DOC,
            ),
        ),
        employees=(pam,),
    )
    assert mismatches == ()


def test_undeclared_outcome_skips_the_check() -> None:
    pam = Employee(id="pam", name="Pam", role="pm")
    mismatches = outcome_mismatches(
        (ChildPlan(label="spec", intent="write the api spec", assignee="pam"),),
        employees=(pam,),
    )
    assert mismatches == ()


def test_unknown_role_fails_open() -> None:
    custom = Employee(id="x", name="X", role="custom_plugin")
    mismatches = outcome_mismatches(
        (
            ChildPlan(
                label="impl",
                intent="build it",
                assignee="x",
                outcome_kind=OutcomeKind.PR,
            ),
        ),
        employees=(custom,),
        catalog=RoleOutcomeCatalog(),
    )
    assert mismatches == ()
