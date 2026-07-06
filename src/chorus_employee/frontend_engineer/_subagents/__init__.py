"""Frontend Engineer subagents — the Code-Reviewer and UI-Tester (review layer).

Two Tier-1, read-only specialists the Frontend Engineer spawns *after* building and running — the
"post-build" quality gate, the structural twins of the Designer's Design-Critic. Each is its own
subpackage: the ``__init__`` carries the :class:`~chorus.roles.SubagentSpec` and its sibling ``_schema``
module holds the pydantic-authored return contract, emitted to the spec's ``output_schema`` so dream
validates the child's final message at runtime.

- **Code-Reviewer** (:mod:`._code_reviewer`) — a read-only adversarial reviewer of the built app and
  its tests: correctness against the intent, accessibility by construction, resilient states,
  maintainability, and (its sharpest lens) whether the tests genuinely prove anything or are hollow.
  Returns a :class:`~._code_reviewer.ReviewVerdict`.
- **UI-Tester** (:mod:`._ui_tester`) — a read-only auditor of the PROOF: it judges whether the e2e
  suite drives the real UI and asserts user-visible outcomes, whether the critical flows are covered,
  and whether the captured runs are real and green. Returns a :class:`~._ui_tester.UiTestVerdict`.

Tier-1, role-owned. Each spec's ``tools`` are CHORUS names (mapped to dream + intersected with the
Frontend Engineer's toolset at materialize — both hold only ``read_file`` / ``working_memory_read`` /
``test_evidence``, all ⊆ the parent, so the projection keeps them). Each spawned child's system prompt
is generated from name + description, so the full brief lives *in* the description — imperative, so the
specialist actually reads the files and returns its verdict rather than claiming it cannot.
"""

from __future__ import annotations

from chorus_employee.frontend_engineer._subagents._code_reviewer import (
    CODE_REVIEWER_SUBAGENT,
    ReviewIssue,
    ReviewVerdict,
    code_review_output_schema,
)
from chorus_employee.frontend_engineer._subagents._ui_tester import (
    UI_TESTER_SUBAGENT,
    CoverageGap,
    UiTestVerdict,
    ui_test_output_schema,
)

__all__ = [
    "CODE_REVIEWER_SUBAGENT",
    "UI_TESTER_SUBAGENT",
    "CoverageGap",
    "ReviewIssue",
    "ReviewVerdict",
    "UiTestVerdict",
    "code_review_output_schema",
    "ui_test_output_schema",
]
