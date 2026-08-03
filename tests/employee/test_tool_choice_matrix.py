"""S0 #10 — Hermes-style tool-choice matrix is wired into craft briefs."""

from __future__ import annotations

import pytest

from chorus_employee._tool_choice import TOOL_CHOICE_MATRIX
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


def test_matrix_is_hermes_use_dont_shape() -> None:
    """Matrix teaches when — not a dump of every verb."""
    assert "TOOL CHOICE" in TOOL_CHOICE_MATRIX
    assert "Use this" in TOOL_CHOICE_MATRIX
    assert "Don't" in TOOL_CHOICE_MATRIX
    for surface in ("tool", "execute_code", "skill", "spawn_subagent", "just implement"):
        assert surface in TOOL_CHOICE_MATRIX.lower()
    # Stay cache-friendly: action-space teaching, not procedure.
    assert len(TOOL_CHOICE_MATRIX.split()) <= 110
    assert "tool > execute_code > skill > spawn" in TOOL_CHOICE_MATRIX


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
def test_craft_brief_includes_tool_choice_matrix(brief: str) -> None:
    assert TOOL_CHOICE_MATRIX in brief
    assert "tool > execute_code > skill > spawn" in brief
