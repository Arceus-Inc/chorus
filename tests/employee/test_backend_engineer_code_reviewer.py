"""Backend Engineer — Code-Reviewer subagent + typed CodeReviewVerdict (spec §06 / §16 Slice 4).

The Code-Reviewer is the third leg of §06's verification swarm (author tests · drive the service ·
RED-TEAM the diff). An independent, in-beat adversary the engineer spawns to hunt the prod-failure
classes that pass their own tests — missing authz, N+1, injection, unbounded query, no rate limit,
secrets in code — and returns a decisive :class:`CodeReviewVerdict`. It reviews, never fixes. These
tests pin the return contract + wiring; the live red-team loop is proven by the keyed e2e.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chorus.roles import role_beat_config
from chorus_employee.backend_engineer import (
    CODE_REVIEWER_SUBAGENT,
    CodeReviewVerdict,
    RiskFinding,
    backend_engineer_plugin,
    code_review_verdict_output_schema,
)
from chorus_harness._factory import _subagent_set

pytestmark = pytest.mark.integration


# --- the typed return contract ---


class TestCodeReviewVerdictSchema:
    def test_cleared_verdict_with_no_high_findings(self) -> None:
        verdict = CodeReviewVerdict(
            cleared=True,
            findings=[
                RiskFinding(
                    category="other",
                    severity="low",
                    location="orders/service.py:40",
                    detail="a nit — magic number",
                    fix="name the constant",
                )
            ],
            evidence="read the full diff; traced every handler's authz + query path",
        )
        assert verdict.cleared is True

    def test_cleared_with_empty_findings_is_valid(self) -> None:
        verdict = CodeReviewVerdict(cleared=True, findings=[], evidence="nothing to flag")
        assert verdict.cleared is True

    def test_cleared_true_with_a_high_finding_is_a_contradiction(self) -> None:
        # You cannot clear a diff while reporting a high-severity risk in it.
        with pytest.raises(ValidationError):
            CodeReviewVerdict(
                cleared=True,
                findings=[
                    RiskFinding(
                        category="missing_authz",
                        severity="high",
                        location="orders/http.py:22",
                        detail="GET /orders/{id} never checks ownership — any user reads any order",
                        fix="assert order.user_id == caller before returning",
                    )
                ],
                evidence="traced the handler",
            )

    def test_not_cleared_verdict_lists_the_findings(self) -> None:
        verdict = CodeReviewVerdict(
            cleared=False,
            findings=[
                RiskFinding(
                    category="n_plus_1",
                    severity="high",
                    location="orders/service.py:55",
                    detail="loads each line item in a loop — N+1 against the DB",
                    fix="batch the fetch with a single IN query",
                )
            ],
            evidence="read the service layer",
        )
        assert verdict.cleared is False
        assert verdict.findings[0].category == "n_plus_1"

    def test_a_finding_requires_location_detail_and_fix(self) -> None:
        with pytest.raises(ValidationError):
            RiskFinding(category="injection", severity="high", location="", detail="x", fix="y")

    def test_output_schema_derives_from_the_model(self) -> None:
        schema = code_review_verdict_output_schema()
        assert schema.get("type") == "object"
        # findings defaults to [] (a clean review), so it's optional; cleared + evidence are required.
        assert {"cleared", "evidence"} <= set(schema["required"])
        assert "findings" in schema["properties"]
        assert schema["properties"]["cleared"]["type"] == "boolean"


# --- the subagent declaration ---


class TestCodeReviewerDeclaration:
    def test_subagent_name(self) -> None:
        assert CODE_REVIEWER_SUBAGENT.name == "code_reviewer"

    def test_carries_the_verdict_output_schema(self) -> None:
        schema = CODE_REVIEWER_SUBAGENT.output_schema
        assert schema is not None
        assert {"cleared", "evidence"} <= set(schema["required"])

    def test_can_read_and_persist_its_verdict(self) -> None:
        # It reads the diff and writes ONLY its own review_verdict.json (independent authorship).
        assert "read_file" in CODE_REVIEWER_SUBAGENT.tools
        assert "write_file" in CODE_REVIEWER_SUBAGENT.tools

    def test_description_reviews_never_patches(self) -> None:
        # A red-teamer reviews; the prompt forbids it from patching production code.
        desc = CODE_REVIEWER_SUBAGENT.description.lower()
        assert "never" in desc and ("patch" in desc or "fix" in desc)
        assert "production" in desc or "the engineer" in desc

    def test_description_names_the_prod_failure_classes(self) -> None:
        desc = CODE_REVIEWER_SUBAGENT.description.lower()
        assert "authz" in desc or "authorization" in desc
        assert "n+1" in desc or "n_plus_1" in desc or "injection" in desc

    def test_max_turns_bounded(self) -> None:
        assert CODE_REVIEWER_SUBAGENT.max_turns <= 10


# --- harness wiring (all three subagents present) ---


class TestCodeReviewerWiring:
    def test_manifest_declares_all_three_subagents(self) -> None:
        names = {sa.name for sa in backend_engineer_plugin().manifest.subagents}
        assert {"api_verifier", "test_author", "code_reviewer"} <= names

    def test_tools_are_a_subset_of_the_parent(self) -> None:
        parent_tools = set(backend_engineer_plugin().manifest.tools)
        for tool in CODE_REVIEWER_SUBAGENT.tools:
            assert tool in parent_tools, f"{tool!r} not in the Backend Engineer's toolset"

    def test_projection_offers_the_code_reviewer_at_runtime(self) -> None:
        config = role_beat_config(backend_engineer_plugin().manifest)
        result = _subagent_set(config)
        assert result is not None
        assert result.get("code_reviewer") is not None


class TestReviewingForProdFailuresSkill:
    def test_the_skill_the_reviewer_points_at_exists(self) -> None:
        from pathlib import Path

        assert "reviewing-for-prod-failures" in CODE_REVIEWER_SUBAGENT.description
        root = backend_engineer_plugin().manifest.skills_root
        assert root is not None
        skill = Path(root) / "reviewing-for-prod-failures" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "authz" in body or "authorization" in body
        assert "n+1" in body or "n_plus_1" in body
        assert "injection" in body
