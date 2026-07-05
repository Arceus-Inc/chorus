"""Backend Engineer — Slice 3a: API-Verifier subagent + typed ApiTestVerdict (spec §16 Slice 3).

The API-Verifier is the backend twin of the Marketer's Brand-Critic: an independent, in-beat grader
the engineer spawns *after* the unit bundle is green. It boots the just-built service on a real port
and probes it over HTTP, returning a decisive :class:`ApiTestVerdict`. These tests pin the return
contract and the harness wiring; the live boot→probe loop is proven by the keyed e2e.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chorus.roles import role_beat_config
from chorus_employee.backend_engineer import (
    API_VERIFIER_SUBAGENT,
    ApiCheck,
    ApiTestVerdict,
    api_test_verdict_output_schema,
    backend_engineer_plugin,
)
from chorus_harness._factory import _subagent_set

pytestmark = pytest.mark.integration


# --- the typed return contract ---


class TestApiTestVerdictSchema:
    def test_passed_verdict_with_all_checks_ok(self) -> None:
        verdict = ApiTestVerdict(
            passed=True,
            checks=[ApiCheck(name="GET /health -> 200", ok=True, detail="200 ok")],
            evidence="booted `python app.py` on 127.0.0.1:8123; curled /health",
        )
        assert verdict.passed is True
        assert verdict.checks[0].ok is True

    def test_failing_verdict_records_the_red_check(self) -> None:
        verdict = ApiTestVerdict(
            passed=False,
            checks=[ApiCheck(name="GET /slugify?s=Hi! -> hi", ok=False, detail="got 'Hi!'")],
            evidence="server booted but /slugify returned the input unchanged",
        )
        assert verdict.passed is False
        assert verdict.checks[0].ok is False

    def test_passed_cannot_be_true_with_a_red_check(self) -> None:
        # The contract is self-consistent: you cannot claim the service passed while a probe failed.
        with pytest.raises(ValidationError):
            ApiTestVerdict(
                passed=True,
                checks=[ApiCheck(name="GET /health", ok=False, detail="connection refused")],
                evidence="server never came up",
            )

    def test_at_least_one_check_is_required(self) -> None:
        # A verdict with no probe issued proves nothing — reject the empty grade.
        with pytest.raises(ValidationError):
            ApiTestVerdict(passed=True, checks=[], evidence="nothing probed")

    def test_evidence_is_required_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            ApiTestVerdict(
                passed=True,
                checks=[ApiCheck(name="GET /health", ok=True, detail="200")],
                evidence="",
            )

    def test_output_schema_derives_from_the_model(self) -> None:
        schema = api_test_verdict_output_schema()
        assert schema.get("type") == "object"
        assert {"passed", "checks", "evidence"} <= set(schema["required"])
        assert schema["properties"]["passed"]["type"] == "boolean"


# --- the subagent declaration ---


class TestApiVerifierDeclaration:
    def test_subagent_name(self) -> None:
        assert API_VERIFIER_SUBAGENT.name == "api_verifier"

    def test_carries_the_verdict_output_schema(self) -> None:
        schema = API_VERIFIER_SUBAGENT.output_schema
        assert schema is not None
        assert schema.get("type") == "object"
        assert {"passed", "checks", "evidence"} <= set(schema["required"])

    def test_can_boot_and_probe_the_service(self) -> None:
        # It needs run_command to start the server + curl it, and write_file to record api_verdict.json.
        assert "run_command" in API_VERIFIER_SUBAGENT.tools
        assert "write_file" in API_VERIFIER_SUBAGENT.tools
        assert "read_file" in API_VERIFIER_SUBAGENT.tools

    def test_description_instructs_a_real_running_probe(self) -> None:
        desc = API_VERIFIER_SUBAGENT.description.lower()
        assert "boot" in desc or "start" in desc
        assert "http" in desc
        assert "api_verdict.json" in desc

    def test_description_says_verify_not_fix(self) -> None:
        desc = API_VERIFIER_SUBAGENT.description.lower()
        assert "not" in desc and "fix" in desc

    def test_max_turns_bounded(self) -> None:
        assert API_VERIFIER_SUBAGENT.max_turns <= 10

    def test_description_proves_durability_for_stateful_services(self) -> None:
        # A stateless boot+curl can't catch a mock: an in-memory fake passes POST->GET too. The
        # verifier must prove persistence survives a RESTART — the real-datastore proof (§16 Slice 3).
        desc = API_VERIFIER_SUBAGENT.description.lower()
        assert "persist" in desc
        assert "restart" in desc


# --- harness wiring ---


class TestApiVerifierWiring:
    def test_manifest_declares_the_api_verifier(self) -> None:
        plugin = backend_engineer_plugin()
        assert any(sa.name == "api_verifier" for sa in plugin.manifest.subagents)

    def test_manifest_grants_spawn_subagent(self) -> None:
        plugin = backend_engineer_plugin()
        assert "spawn_subagent" in plugin.manifest.tools

    def test_verifier_tools_are_a_subset_of_the_parent(self) -> None:
        plugin = backend_engineer_plugin()
        parent_tools = set(plugin.manifest.tools)
        for tool in API_VERIFIER_SUBAGENT.tools:
            assert tool in parent_tools, f"{tool!r} not in the Backend Engineer's toolset"

    def test_beat_config_carries_the_subagent(self) -> None:
        config = role_beat_config(backend_engineer_plugin().manifest)
        assert {sa.name for sa in config.subagents} == {"api_verifier"}

    def test_projection_offers_the_verifier_at_runtime(self) -> None:
        config = role_beat_config(backend_engineer_plugin().manifest)
        result = _subagent_set(config)
        assert result is not None
        child = result.get("api_verifier")
        assert child is not None
        # The projection maps chorus tool names to dream's — run_command -> bash — and intersects with
        # the parent's live toolset, so the child carries the dream name here.
        assert "bash" in child.tools
