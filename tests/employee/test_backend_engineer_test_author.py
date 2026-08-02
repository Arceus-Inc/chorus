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
            red_evidence="ran `pytest -q` before impl — 4 failed (ModuleNotFoundError: divide)",
            evidence="ran `pytest -q` — 4 passed",
        )
        assert verdict.authored is True
        assert verdict.files == ["test_divide.py"]
        assert "failed" in verdict.red_evidence

    def test_not_authored_verdict_may_be_empty(self) -> None:
        # A non-authored verdict needs no RED proof — there were no tests to see fail.
        verdict = TestPlanVerdict(
            authored=False, files=[], covers=[], evidence="the change had no testable behaviour"
        )
        assert verdict.authored is False
        assert verdict.red_evidence == ""

    def test_authored_requires_at_least_one_file(self) -> None:
        # Claiming tests were authored while writing none is a contradiction.
        with pytest.raises(ValidationError):
            TestPlanVerdict(
                authored=True, files=[], covers=["x"], red_evidence="saw it fail", evidence="green"
            )

    def test_authored_requires_named_coverage(self) -> None:
        with pytest.raises(ValidationError):
            TestPlanVerdict(
                authored=True,
                files=["t.py"],
                covers=[],
                red_evidence="saw it fail",
                evidence="green",
            )

    def test_evidence_is_required_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            TestPlanVerdict(
                authored=True, files=["t.py"], covers=["x"], red_evidence="saw it fail", evidence=""
            )

    def test_authored_requires_red_evidence(self) -> None:
        # TDD's core invariant: you cannot claim authored tests without having seen them fail FIRST.
        with pytest.raises(ValidationError):
            TestPlanVerdict(
                authored=True, files=["t.py"], covers=["x"], red_evidence="", evidence="4 passed"
            )

    def test_output_schema_derives_from_the_model(self) -> None:
        schema = plan_verdict_output_schema()
        assert schema.get("type") == "object"
        assert {"authored", "files", "covers", "evidence"} <= set(schema["required"])
        assert "red_evidence" in schema["properties"]
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
        assert "test_red" in TEST_AUTHOR_SUBAGENT.tools

    def test_test_plan_is_a_required_independent_artifact(self) -> None:
        assert TEST_AUTHOR_SUBAGENT.evidence_path == "test_plan.json"
        assert TEST_AUTHOR_SUBAGENT.evidence_claim == {"authored": True}
        assert TEST_AUTHOR_SUBAGENT.evidence_read_only is False

    def test_description_writes_tests_never_production_code(self) -> None:
        desc = TEST_AUTHOR_SUBAGENT.description.lower()
        assert "test" in desc
        assert "never" in desc and "production" in desc

    def test_description_mentions_the_honeycomb_shape(self) -> None:
        assert "honeycomb" in TEST_AUTHOR_SUBAGENT.description.lower()

    def test_description_is_test_first_red(self) -> None:
        # The RED-author writes the failing test BEFORE the implementation exists (TDD).
        desc = TEST_AUTHOR_SUBAGENT.description.lower()
        assert "red" in desc
        assert "before" in desc and "implement" in desc
        assert "red_evidence" in desc  # it must record the failing run it saw first
        assert "test_red" in desc
        assert "refuse" in desc and "production" in desc
        assert "expected_failure" in desc

    def test_greenfield_missing_target_is_valid_red_but_unrelated_import_failure_is_not(
        self,
    ) -> None:
        desc = TEST_AUTHOR_SUBAGENT.description.lower()
        assert "missing target module" in desc
        assert "valid red" in desc
        assert "unrelated" in desc and "import" in desc

    def test_description_forbids_inventing_an_unassigned_contract(self) -> None:
        desc = TEST_AUTHOR_SUBAGENT.description.lower()
        assert "do not invent" in desc
        assert "assigned acceptance criteria" in desc
        assert "unrelated api" in desc

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


class TestTestingHoneycombSkill:
    def test_the_skill_the_test_author_points_at_exists(self) -> None:
        # The RED-author is told to consult `testing-honeycomb-strategy` — the pointer must resolve.
        from pathlib import Path

        assert "testing-honeycomb-strategy" in TEST_AUTHOR_SUBAGENT.description
        assert "test-driven-development" in TEST_AUTHOR_SUBAGENT.description
        root = backend_engineer_plugin().manifest.skills_root
        assert root is not None
        skill = Path(root) / "testing-honeycomb-strategy" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "honeycomb" in body
        assert "red" in body  # test-first: see it fail before implementing
        assert "integration" in body  # the honeycomb's heavy middle

    def test_no_dead_skill_pointer(self) -> None:
        # We dropped the testcontainers pointer — don't point at a skill that isn't authored.
        assert "testcontainers-integration" not in TEST_AUTHOR_SUBAGENT.description
