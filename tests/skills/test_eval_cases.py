"""Eval cases stay pinned to one immutable skill revision."""

from __future__ import annotations

import uuid

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


def test_eval_case_cannot_reference_another_company_revision(pg_database: str) -> None:
    company_a = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    company_b = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        skill = company_a.skills.insert(
            Skill(
                id=uid("foreign-skill"),
                employee_id="bex",
                slug="foreign-skill",
                name="Foreign Skill",
                origin=SkillOrigin.CREATED,
            )
        )
        revision = company_a.skill_revisions.append(
            SkillRevision(
                id=uid("foreign-revision"),
                skill_id=skill.id,
                revision_no=1,
                action="create",
                file_inventory="[]",
                content_hash="foreign-v1",
            )
        )

        with pytest.raises(Exception):
            company_b.eval_cases.create(
                EvalCase(
                    id=uid("cross-company-case"),
                    skill_revision_id=revision.id,
                    name="must stay isolated",
                    input_text="Attempt a cross-company reference.",
                    expected_behavior="Reject it.",
                )
            )
    finally:
        company_b._conn.rollback()
        company_a.close()
        company_b.close()
