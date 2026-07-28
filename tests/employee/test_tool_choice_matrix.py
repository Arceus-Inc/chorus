"""Workforce tool-choice / resume / recall live in Dream core-beliefs, not craft briefs."""

from __future__ import annotations

import pytest

from chorus_employee.analyst._brief import ANALYST_BRIEF
from chorus_employee.backend_engineer._brief import BACKEND_ENGINEER_BRIEF
from chorus_employee.ceo._brief import CEO_BRIEF
from chorus_employee.designer._brief import DESIGNER_BRIEF
from chorus_employee.engineer._brief import ENGINEER_BRIEF
from chorus_employee.frontend_engineer._brief import FRONTEND_ENGINEER_BRIEF
from chorus_employee.marketer._brief import MARKETER_BRIEF
from chorus_employee.pm._brief import PM_BRIEF
from dream.services.core_beliefs import extract_standing_orders, packaged_core_beliefs_path

pytestmark = pytest.mark.unit

_CRAFT_BRIEFS = (
    BACKEND_ENGINEER_BRIEF,
    FRONTEND_ENGINEER_BRIEF,
    ENGINEER_BRIEF,
    PM_BRIEF,
    MARKETER_BRIEF,
    DESIGNER_BRIEF,
    ANALYST_BRIEF,
    CEO_BRIEF,
)


def test_workforce_waist_lives_in_dream_core_beliefs() -> None:
    orders = extract_standing_orders(packaged_core_beliefs_path())
    joined = "\n".join(orders.always)
    assert "You are an employee of a AI Workforce" in joined
    assert "TOOL CHOICE" in joined
    assert "todo_write" in joined


@pytest.mark.parametrize(
    "brief",
    _CRAFT_BRIEFS,
    ids=(
        "backend_engineer",
        "frontend_engineer",
        "engineer",
        "pm",
        "marketer",
        "designer",
        "analyst",
        "ceo",
    ),
)
def test_craft_brief_is_employee_specific_not_shared_waist(brief: str) -> None:
    assert "You are an employee of a AI Workforce" not in brief
    assert "RESUME, DON'T RESTART" not in brief
    assert "EPISODIC MEMORY:" not in brief
    assert "TOOL CHOICE" not in brief
