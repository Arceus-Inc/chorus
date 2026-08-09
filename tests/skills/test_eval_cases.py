"""Eval cases stay pinned to one immutable skill revision."""

from __future__ import annotations

import pytest

from chorus.ledger import EvalCase, Ledger, Skill, SkillOrigin, SkillRevision
from chorus.testing import uid

pytestmark = pytest.mark.unit


def test_eval_case_pins_exact_skill_revision_after_head_advances(ledger: Ledger) -> None:
    skill = ledger.skills.insert(
        Skill(
            id=uid("skill"),
            employee_id="bex",
            slug="structured-service",
            name="Structured Service",
            origin=SkillOrigin.CREATED,
        )
    )
    revision_one = ledger.skill_revisions.append(
        SkillRevision(
            id=uid("revision-one"),
            skill_id=skill.id,
            revision_no=1,
            action="create",
            file_inventory="[]",
            content_hash="v1",
        )
    )
    case = ledger.eval_cases.create(
        EvalCase(
            id=uid("case"),
            skill_revision_id=revision_one.id,
            name="rejects ambiguous requirements",
            input_text="Build the thing.",
            expected_behavior="Ask for the missing requirement.",
        )
    )

    revision_two = ledger.skill_revisions.append(
        SkillRevision(
            id=uid("revision-two"),
            skill_id=skill.id,
            revision_no=2,
            action="patch",
            file_inventory="[]",
            content_hash="v2",
        )
    )

    assert ledger.skill_revisions.head(skill.id) == revision_two
    assert ledger.eval_cases.get(case.id) == case
    assert ledger.eval_cases.by_skill_revision(revision_one.id) == [case]
    assert ledger.eval_cases.by_skill_revision(revision_two.id) == []
