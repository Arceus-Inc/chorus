"""The Backend Engineer's §16 Slice 3 verification library skills (spec §11): real-DB integration,
property-based API conformance, and consumer-driven contracts. These pin that the manifest carries
each skill, the file exists with the right anchors, and the api_verifier's prompt actually routes to
them (a dangling reference to a skill that doesn't exist is worse than no reference).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus_employee.backend_engineer import backend_engineer_plugin
from chorus_employee.backend_engineer._subagents import API_VERIFIER_SUBAGENT, ApiTestVerdict

pytestmark = pytest.mark.unit


class TestTestcontainersIntegrationSkill:
    def test_manifest_carries_the_skill(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert "testcontainers-integration" in manifest.skills
        assert manifest.skills_root is not None

    def test_the_skill_file_exists_and_warns_off_fakes(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert manifest.skills_root is not None
        skill = Path(manifest.skills_root) / "testcontainers-integration" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "health-gate" in body or "health gate" in body
        assert "sqlite" in body  # names the specific fake-swap-in trap

    def test_api_verifier_prompt_routes_durability_through_the_skill(self) -> None:
        prompt = API_VERIFIER_SUBAGENT.description
        assert "testcontainers-integration" in prompt

    def test_api_verifier_prompt_mandates_a_real_container_for_client_server_datastores(
        self,
    ) -> None:
        # A live run proved this was previously a suggestion, not a requirement: the one datastore
        # smoke run exercised only embedded SQLite (no container needed), leaving the container-boot
        # path untested and, worse, unenforced for a Postgres/Mongo/Redis-backed service. The prompt
        # must draw the embedded-vs-client-server line and make the container a MUST, not a maybe.
        prompt = API_VERIFIER_SUBAGENT.description
        assert "MUST boot the real engine as a DISPOSABLE CONTAINER" in prompt
        assert "EMBEDDED" in prompt and "CLIENT-SERVER" in prompt
        # names the specific fakes it must reject, not just "a mock"
        assert "fakeredis" in prompt
        assert "mongomock" in prompt

    def test_evidence_schema_demands_the_container_boot_command_for_client_server_stores(
        self,
    ) -> None:
        # The typed contract, not just prose: evidence must name the exact container command/image —
        # so "connected to db" (true for a fake too) doesn't satisfy the field.
        schema = ApiTestVerdict.model_json_schema()
        evidence_desc = schema["properties"]["evidence"]["description"]
        assert "docker" in evidence_desc.lower()


class TestPropertyTestingSchemathesisSkill:
    def test_manifest_carries_the_skill(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert "property-testing-schemathesis" in manifest.skills

    def test_the_skill_file_exists_and_names_the_tool(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert manifest.skills_root is not None
        skill = Path(manifest.skills_root) / "property-testing-schemathesis" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "schemathesis" in body
        assert "openapi" in body

    def test_api_verifier_prompt_references_the_skill(self) -> None:
        assert "property-testing-schemathesis" in API_VERIFIER_SUBAGENT.description


class TestContractTestingPactSkill:
    def test_manifest_carries_the_skill(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert "contract-testing-pact" in manifest.skills

    def test_the_skill_file_exists_and_names_the_tool(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert manifest.skills_root is not None
        skill = Path(manifest.skills_root) / "contract-testing-pact" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "pact" in body
        assert "consumer" in body

    def test_api_verifier_prompt_references_the_skill(self) -> None:
        assert "contract-testing-pact" in API_VERIFIER_SUBAGENT.description


class TestMutationTestingSkill:
    def test_manifest_carries_the_skill(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert "mutation-testing" in manifest.skills

    def test_the_skill_file_exists_and_teaches_kill_rate_over_coverage(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert manifest.skills_root is not None
        skill = Path(manifest.skills_root) / "mutation-testing" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "kill rate" in body or "kill-rate" in body
        assert "survivor" in body  # names the core concept a survivor == an unguarded behaviour
        assert "coverage" in body  # contrasts against the weaker signal it replaces
        # names a concrete stack tool so the engineer isn't inventing one under time pressure
        assert "mutmut" in body

    def test_brief_routes_real_logic_through_mutation_and_gates_it_in_test_evidence(self) -> None:
        # It must be a test_evidence gate (reuses the proof primitive), scoped to real-logic changes,
        # and explicitly forbid gaming — the same discipline as the lint/secret gates.
        brief = backend_engineer_plugin().manifest.system_prompt
        assert "mutation-testing" in brief
        assert "mutation" in brief and "test_evidence" in brief
        assert "NEVER weaken the tool" in brief


class TestMigrationRoundtripSkill:
    def test_manifest_carries_the_skill(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert "migration-roundtrip" in manifest.skills

    def test_the_skill_file_exists_and_teaches_the_full_round_trip(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert manifest.skills_root is not None
        skill = Path(manifest.skills_root) / "migration-roundtrip" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "roll back" in body or "rollback" in body
        assert "re-apply" in body  # the full round-trip, not just apply+rollback
        assert "one-way door" in body  # names the failure it prevents
        assert "sqlite" in body  # warns off the fake-engine trap for DDL

    def test_brief_routes_migrations_through_roundtrip_and_gates_it_in_test_evidence(self) -> None:
        brief = backend_engineer_plugin().manifest.system_prompt
        assert "migration-roundtrip" in brief
        assert "migration" in brief and "test_evidence" in brief
        assert "roll back" in brief or "rollback" in brief
        assert "re-apply" in brief


def test_api_verifier_prompt_no_longer_dangles_a_slice4_skill_reference() -> None:
    # load-testing-slo-gates is §16 Slice 4 (deferred) — no such skill file exists yet. Referencing it
    # from the api_verifier prompt was a dangling pointer; Slice 3 only wires the skills that ship now.
    assert "load-testing-slo-gates" not in API_VERIFIER_SUBAGENT.description
