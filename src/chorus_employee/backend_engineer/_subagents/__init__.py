"""The Backend Engineer's Tier-1 subagents — each a subpackage carrying its spec + return contract.

Currently one: the :data:`API_VERIFIER_SUBAGENT`, an independent grader that boots the built service
and probes it over real HTTP (spec §16 Slice 3). The manifest declares it; the composition root
projects it onto dream's subagent set, intersecting its tools with the parent's (narrower-wins).
"""

from __future__ import annotations

from chorus_employee.backend_engineer._subagents._api_verifier import (
    API_VERIFIER_SUBAGENT,
    ApiCheck,
    ApiTestVerdict,
    api_test_verdict_output_schema,
)
from chorus_employee.backend_engineer._subagents._test_author import (
    TEST_AUTHOR_SUBAGENT,
    TestPlanVerdict,
    plan_verdict_output_schema,
)

__all__ = [
    "API_VERIFIER_SUBAGENT",
    "TEST_AUTHOR_SUBAGENT",
    "ApiCheck",
    "ApiTestVerdict",
    "TestPlanVerdict",
    "api_test_verdict_output_schema",
    "plan_verdict_output_schema",
]
