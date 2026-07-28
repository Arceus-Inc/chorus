"""The Frontend Engineer's brief must be lean and principled — character, not law.

Per docs/plans/2026-07-18-hooks-and-briefs-research.md §B (podium repo): briefs carry identity,
autonomy stance, communication contract, ranked judgment priorities, ending discipline, and a
pointer to procedures — everything else lives on the tools (self-describing) or in the skills
(deep procedure). Enforced prohibitions live in gates, not prose: instruction blocks past ~3k
tokens degrade reasoning, and omission constraints decay in long contexts.
"""

from __future__ import annotations

import pytest

from chorus_employee.frontend_engineer._brief import FRONTEND_ENGINEER_BRIEF

pytestmark = pytest.mark.unit


def test_brief_fits_the_lean_token_budget() -> None:
    """The brief stays under ~1050 tokens (words * 4/3 heuristic).

    docs/plans/2026-07-18-hooks-and-briefs-research.md §B: target <~600 tokens for character;
    hard budget 1050 includes the Hermes-style tool-choice matrix (S0 #10). Gates carry the law.
    """
    assert len(FRONTEND_ENGINEER_BRIEF.split()) * 4 / 3 <= 1050


def test_brief_keeps_the_anatomy_essentials() -> None:
    """Identity survives the diet: subagents by name, manager escalation, deliverable class."""
    brief = FRONTEND_ENGINEER_BRIEF
    for subagent in ("code_reviewer", "ui_tester"):
        assert subagent in brief, subagent
    assert "manager" in brief.lower()  # escalate-to-manager communication norm
    assert "PR" in brief  # the deliverable artifact class it lands
    assert "test_evidence" in brief  # the durable evidence bundle it leaves
