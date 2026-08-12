"""Workforce standing orders stay out of craft briefs."""

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
def test_craft_brief_excludes_the_shared_workforce_waist(brief: str) -> None:
    for marker in ("TOOL CHOICE", "RESUME, DON'T RESTART", "EPISODIC MEMORY"):
        assert marker not in brief
