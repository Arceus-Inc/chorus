"""Backend Engineer — the Test-Author subagent + typed TestPlanVerdict (spec §06 / §16 Slice 4).

The Test-Author is the 'pre' layer of §06's validation sandwich: an independent, in-beat specialist
the engineer spawns to write honeycomb-shaped tests for the change — so the code's author is not the
sole author of its tests. It writes tests, never production code, and returns a decisive
:class:`TestPlanVerdict`. These tests pin the return contract and the harness wiring; the live
author→run loop is proven by the keyed e2e.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chorus.roles import role_beat_config
from chorus_employee.backend_engineer import (
    TEST_AUTHOR_SUBAGENT,
    TestPlanVerdict,
    backend_engineer_plugin,
    plan_verdict_output_schema,
)
from chorus_harness._factory import _subagent_set

pytestmark = pytest.mark.integration


# --- the typed return contract ---


class TestTestPlanVerdictSchema:
    def test_authored_verdict_lists_files_and_coverage(self) -> None:
        verdict = TestPlanVerdict(
            authored=True,
            files=["test_divide.py"],
            covers=["divide happy path", "divide by zero raises ValueError"],
            evidence="ran `pytest -q` — 4 passed",
        )
        assert verdict.authored is True
        assert verdict.files == ["test_divide.py"]

    def test_not_authored_verdict_may_be_empty(self) -> None:
        verdict = TestPlanVerdict(
            authored=False, files=[], covers=[], evidence="the change had no testable behaviour"
        )
        assert verdict.authored is False

    def test_authored_requires_at_least_one_file(self) -> None:
        # Claiming tests were authored while writing none is a contradiction.
        with pytest.raises(ValidationError):
            TestPlanVerdict(authored=True, files=[], covers=["x"], evidence="ran green")

    def test_authored_requires_named_coverage(self) -> None:
        with pytest.raises(ValidationError):
            TestPlanVerdict(authored=True, files=["t.py"], covers=[], evidence="ran green")

    def test_evidence_is_required_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            TestPlanVerdict(authored=True, files=["t.py"], covers=["x"], evidence="")

    def test_output_schema_derives_from_the_model(self) -> None:
        schema = plan_verdict_output_schema()
        assert schema.get("type") == "object"
        assert {"authored", "files", "covers", "evidence"} <= set(schema["required"])
        assert schema["properties"]["authored"]["type"] == "boolean"


# --- the subagent declaration ---


class TestTestAuthorDeclaration:
    def test_subagent_name(self) -> None:
        assert TEST_AUTHOR_SUBAGENT.name == "test_author"

    def test_carries_the_verdict_output_schema(self) -> None:
        schema = TEST_AUTHOR_SUBAGENT.output_schema
        assert schema is not None
        assert {"authored", "files", "covers", "evidence"} <= set(schema["required"])

    def test_can_write_and_run_tests(self) -> None:
        assert "write_file" in TEST_AUTHOR_SUBAGENT.tools
        assert "run_command" in TEST_AUTHOR_SUBAGENT.tools
        assert "read_file" in TEST_AUTHOR_SUBAGENT.tools

    def test_description_writes_tests_never_production_code(self) -> None:
        desc = TEST_AUTHOR_SUBAGENT.description.lower()
        assert "test" in desc
        assert "never" in desc and "production" in desc

    def test_description_mentions_the_honeycomb_shape(self) -> None:
        assert "honeycomb" in TEST_AUTHOR_SUBAGENT.description.lower()

    def test_max_turns_bounded(self) -> None:
        assert TEST_AUTHOR_SUBAGENT.max_turns <= 10


# --- harness wiring (both subagents present) ---


class TestTestAuthorWiring:
    def test_manifest_declares_both_subagents(self) -> None:
        names = {sa.name for sa in backend_engineer_plugin().manifest.subagents}
        assert {"api_verifier", "test_author"} <= names

    def test_test_author_tools_are_a_subset_of_the_parent(self) -> None:
        parent_tools = set(backend_engineer_plugin().manifest.tools)
        for tool in TEST_AUTHOR_SUBAGENT.tools:
            assert tool in parent_tools, f"{tool!r} not in the Backend Engineer's toolset"

    def test_projection_offers_the_test_author_at_runtime(self) -> None:
        config = role_beat_config(backend_engineer_plugin().manifest)
        result = _subagent_set(config)
        assert result is not None
        assert result.get("test_author") is not None
