"""The Backend Engineer's Tier-1 subagents — each a subpackage carrying its spec + return contract.

The §06 verification swarm: the :data:`TEST_AUTHOR_SUBAGENT` writes the failing tests first (TDD),
the :data:`API_VERIFIER_SUBAGENT` proves the built service runs over real HTTP (spec §16 Slice 3),
and the :data:`CODE_REVIEWER_SUBAGENT` red-teams the diff for the prod-failure classes tests miss.
The manifest declares them; the composition root projects them onto dream's subagent set,
intersecting each one's tools with the parent's (narrower-wins).
"""

from __future__ import annotations

from chorus_employee.backend_engineer._subagents._api_verifier import (
    API_VERIFIER_SUBAGENT,
    ApiCheck,
    ApiTestVerdict,
    api_test_verdict_output_schema,
)
from chorus_employee.backend_engineer._subagents._code_reviewer import (
    CODE_REVIEWER_SUBAGENT,
    CodeReviewVerdict,
    RiskFinding,
    code_review_verdict_output_schema,
)
from chorus_employee.backend_engineer._subagents._test_author import (
    TEST_AUTHOR_SUBAGENT,
    TestPlanVerdict,
    plan_verdict_output_schema,
)

__all__ = [
    "API_VERIFIER_SUBAGENT",
    "CODE_REVIEWER_SUBAGENT",
    "TEST_AUTHOR_SUBAGENT",
    "ApiCheck",
    "ApiTestVerdict",
    "CodeReviewVerdict",
    "RiskFinding",
    "TestPlanVerdict",
    "api_test_verdict_output_schema",
    "code_review_verdict_output_schema",
    "plan_verdict_output_schema",
]
