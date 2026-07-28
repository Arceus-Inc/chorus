"""S0 #10 — Hermes-style tool-choice lives in Dream Base Prompt, not craft briefs."""

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
from dream.prompts.employee_base import (
    EMPLOYEE_BASE_PROMPT,
    TOOL_CHOICE_MATRIX,
    render_employee_base_prompt,
)

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


def test_matrix_lives_in_dream_base_prompt() -> None:
    assert "TOOL CHOICE" in TOOL_CHOICE_MATRIX
    assert "Use this" in TOOL_CHOICE_MATRIX
    assert EMPLOYEE_BASE_PROMPT.startswith("You are an employee of a AI Workforce")
    rendered = render_employee_base_prompt(
        tool_names=("skill", "spawn_subagent", "todo_write", "recall")
    )
    assert TOOL_CHOICE_MATRIX in rendered


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
def test_craft_brief_is_employee_specific_not_shared_matrix(brief: str) -> None:
    """Briefs stay craft-only; Dream injects the shared waist at session assemble."""
    assert TOOL_CHOICE_MATRIX not in brief
    assert "You are an employee of a AI Workforce" not in brief
    assert "RESUME, DON'T RESTART" not in brief
    assert "EPISODIC MEMORY:" not in brief
