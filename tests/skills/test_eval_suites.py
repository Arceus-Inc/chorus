"""Eval suites pin an ordered set of cases to one immutable skill revision."""

from __future__ import annotations

import uuid

import pytest

from chorus.ledger import EvalCase, EvalSuite, Ledger, Skill, SkillOrigin, SkillRevision
from chorus.testing import uid

pytestmark = pytest.mark.unit


def _revision(ledger: Ledger, *, suffix: str, revision_no: int) -> SkillRevision:
    skill = ledger.skills.insert(
        Skill(
            id=uid(f"suite-skill-{suffix}"),
            employee_id="bex",
            slug=f"suite-skill-{suffix}",
            name="Suite Skill",
            origin=SkillOrigin.CREATED,
        )
    )
    return ledger.skill_revisions.append(
        SkillRevision(
            id=uid(f"suite-revision-{suffix}"),
            skill_id=skill.id,
            revision_no=revision_no,
            action="create",
            file_inventory="[]",
            content_hash=suffix,
        )
    )


def _case(ledger: Ledger, *, suffix: str, revision_id: str) -> EvalCase:
    return ledger.eval_cases.create(
        EvalCase(
            id=uid(f"suite-case-{suffix}"),
            skill_revision_id=revision_id,
            name=f"Case {suffix}",
            input_text=f"Input {suffix}",
            expected_behavior=f"Expected {suffix}",
        )
    )


def test_eval_suite_pins_ordered_cases_to_exact_revision_after_head_advances(ledger: Ledger) -> None:
    revision_one = _revision(ledger, suffix="one", revision_no=1)
    first = _case(ledger, suffix="first", revision_id=revision_one.id)
    second = _case(ledger, suffix="second", revision_id=revision_one.id)
    suite = ledger.eval_suites.create(
        EvalSuite(
            id=uid("suite"),
            skill_revision_id=revision_one.id,
            case_ids=(second.id, first.id),
        )
    )

    revision_two = ledger.skill_revisions.append(
        SkillRevision(
            id=uid("suite-revision-two"),
            skill_id=revision_one.skill_id,
            revision_no=2,
            action="patch",
            file_inventory="[]",
            content_hash="two",
        )
    )

    assert ledger.skill_revisions.head(revision_one.skill_id) == revision_two
    assert ledger.eval_suites.get(suite.id) == suite
    assert ledger.eval_suites.by_skill_revision(revision_one.id) == [suite]
    assert ledger.eval_suites.by_skill_revision(revision_two.id) == []


def test_eval_suite_rejects_duplicate_case_membership() -> None:
    case_id = uid("duplicate-case")

    with pytest.raises(ValueError, match="duplicate"):
        EvalSuite(
            id=uid("duplicate-suite"),
            skill_revision_id=uid("revision"),
            case_ids=(case_id, case_id),
        )


def test_eval_suite_rejects_cases_from_another_revision(ledger: Ledger) -> None:
    revision_one = _revision(ledger, suffix="one", revision_no=1)
    revision_two = _revision(ledger, suffix="two", revision_no=1)
    foreign_case = _case(ledger, suffix="foreign", revision_id=revision_two.id)

    with pytest.raises(Exception):
        ledger.eval_suites.create(
            EvalSuite(
                id=uid("cross-revision-suite"),
                skill_revision_id=revision_one.id,
                case_ids=(foreign_case.id,),
            )
        )

    assert ledger.eval_suites.get(uid("cross-revision-suite")) is None


def test_eval_suite_rejects_cases_from_another_company(pg_database: str) -> None:
    company_a = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    company_b = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        foreign_revision = _revision(company_a, suffix="foreign", revision_no=1)
        foreign_case = _case(company_a, suffix="foreign", revision_id=foreign_revision.id)
        local_revision = _revision(company_b, suffix="local", revision_no=1)

        with pytest.raises(Exception):
            company_b.eval_suites.create(
                EvalSuite(
                    id=uid("cross-company-suite"),
                    skill_revision_id=local_revision.id,
                    case_ids=(foreign_case.id,),
                )
            )
    finally:
        company_b._conn.rollback()
        company_a.close()
        company_b.close()
