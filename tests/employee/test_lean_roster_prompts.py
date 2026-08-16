"""No employee brief or tool recovery hint may instruct spawning a removed persona."""

from __future__ import annotations

import re

import pytest

from chorus_employee.analyst import ANALYST_BRIEF
from chorus_employee.ceo import CEO_BRIEF
from chorus_employee.designer import DESIGNER_BRIEF
from chorus_employee.frontend_engineer import FRONTEND_ENGINEER_BRIEF
from chorus_employee.marketer import MARKETER_BRIEF
from chorus_employee.pm import PM_BRIEF
from chorus_tools._record_decision import RecordDecisionTool

pytestmark = pytest.mark.unit

_REMOVED = frozenset(
    {
        "strategist",
        "creative",
        "researcher",
        "advisor",
        "ux_researcher",
        "explorer",
        "ui_tester",
        "data",
        "modeling",
        "narrative",
        "scout",
    }
)

_SPAWN_NAME = re.compile(r"""spawn_subagent\(\s*name\s*=\s*['\"]([^'\"]+)['\"]""")


@pytest.mark.parametrize(
    "brief",
    [
        ANALYST_BRIEF,
        CEO_BRIEF,
        DESIGNER_BRIEF,
        FRONTEND_ENGINEER_BRIEF,
        MARKETER_BRIEF,
        PM_BRIEF,
    ],
    ids=["analyst", "ceo", "designer", "frontend_engineer", "marketer", "pm"],
)
def test_brief_does_not_instruct_spawning_a_removed_name(brief: str) -> None:
    instructed = set(_SPAWN_NAME.findall(brief))
    assert instructed.isdisjoint(_REMOVED), instructed


def test_record_decision_recovery_does_not_name_researcher() -> None:
    hint = RecordDecisionTool._below_floor
    # The recovery copy is built in _below_floor; pin the live next_actions string.
    from chorus_tools._record_decision import RecordDecisionInput

    result = hint(
        RecordDecisionInput(
            option="x",
            rationale="y",
            confidence=0.1,
            outcome_metric="z",
            revisit_trigger="t",
            rejected_alternatives=[],
            claims=[],
        )
    )
    actions = result.structured["next_actions"]
    assert any("web_research" in action for action in actions)
    assert all("researcher" not in action for action in actions)
