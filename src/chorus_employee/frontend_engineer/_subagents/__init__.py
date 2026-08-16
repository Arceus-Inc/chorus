"""Frontend Engineer subagents — lean isolation earners (Code-Reviewer).

The Code-Reviewer is the retained Tier-1 specialist: a read-only adversarial
review of the built app and its tests. UI proof lives as skills
(``playwright-e2e-authoring``, ``test-evidence-discipline``) plus Dream ``verify``.
"""

from __future__ import annotations

from chorus_employee.frontend_engineer._subagents._code_reviewer import (
    CODE_REVIEWER_SUBAGENT,
    ReviewIssue,
    ReviewVerdict,
    code_review_output_schema,
)
from chorus_employee.frontend_engineer._subagents._ui_tester import (
    CoverageGap,
    UiTestVerdict,
    ui_test_output_schema,
)

__all__ = [
    "CODE_REVIEWER_SUBAGENT",
    "CoverageGap",
    "ReviewIssue",
    "ReviewVerdict",
    "UiTestVerdict",
    "code_review_output_schema",
    "ui_test_output_schema",
]
