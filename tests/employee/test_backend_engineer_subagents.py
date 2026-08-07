"""Backend Engineer — Slice 3a: API-Verifier subagent + typed ApiTestVerdict (spec §16 Slice 3).

The API-Verifier is the backend twin of the Marketer's Brand-Critic: an independent, in-beat grader
the engineer spawns *after* the unit bundle is green. It boots the just-built service on a real port
and probes it over HTTP, returning a decisive :class:`ApiTestVerdict`. These tests pin the return
contract and the harness wiring; the live boot→probe loop is proven by the keyed e2e.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dream.skills import load_skill_registry
from pydantic import ValidationError

from chorus.roles import DREAM_DEFAULT_MAX_SPRINTS, role_beat_config
from chorus_employee.backend_engineer import (
    API_VERIFIER_SUBAGENT,
    CODE_REVIEWER_SUBAGENT,
    TEST_AUTHOR_SUBAGENT,
    ApiCheck,
    ApiTestVerdict,
    api_test_verdict_output_schema,
    backend_engineer_plugin,
)
from chorus_harness._factory import _subagent_set, dream_tool_names
from chorus_harness._factory import default_registry as _dream_default_registry

pytestmark = pytest.mark.integration


class TestTodoWriteResumption:
    """Bex carries the durable-checklist tool so a build survives across beats (resumption Slice A).

    ``todo_write`` is a dream builtin that atomically writes ``TODO.md`` to the worktree — durable, not
    in-context. Granting it + a read-first/reconcile brief lets a re-dispatched beat resume where the
    last left off instead of restarting. These pin the wiring; the brief carries the protocol.
    """

    def test_manifest_grants_todo_write(self) -> None:
        assert "todo_write" in backend_engineer_plugin().manifest.tools

    def test_todo_write_maps_to_a_real_dream_builtin(self) -> None:
        # The factory must KEEP todo_write in the chorus->dream map (it was silently dropped before),
        # and it must resolve to an actual dream builtin so the harness enables it.
        assert dream_tool_names(("todo_write",)) == ("todo_write",)
        assert _dream_default_registry().get("todo_write") is not None


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


class TestCodeReviewerEvidenceDeclaration:
    def test_review_verdict_is_a_required_independent_artifact(self) -> None:
        assert CODE_REVIEWER_SUBAGENT.evidence_path == "review_verdict.json"
        assert CODE_REVIEWER_SUBAGENT.evidence_claim == {"cleared": True}


class TestSubagentExecutionPolicy:
    def test_backend_specialists_all_use_delegation(self) -> None:
        assert not hasattr(TEST_AUTHOR_SUBAGENT, "execution_mode")
        assert not hasattr(CODE_REVIEWER_SUBAGENT, "execution_mode")
        assert not hasattr(API_VERIFIER_SUBAGENT, "execution_mode")


# --- the beat time budget (the heaviest beat: build a running service, boot it, restart it, verify) ---


class TestBackendEngineerBeatBudget:
    def test_craft_sprint_budget_matches_dream_default(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert manifest.max_sprints == DREAM_DEFAULT_MAX_SPRINTS

    def test_beat_timeout_is_sized_for_the_full_sandwich(self) -> None:
        # The backend beat must leave room for one evaluator correction sprint and its terminal
        # independent re-review after the build, mutation, and durability gates complete.
        manifest = backend_engineer_plugin().manifest
        assert manifest.beat_timeout_s is not None
        assert manifest.beat_timeout_s >= 1200.0

    def test_lease_ttl_outlives_the_beat_timeout(self) -> None:
        # The stale-run reaper must not claim a beat that is still legitimately running: the run lease
        # has to outlive the beat's own wall-clock budget.
        manifest = backend_engineer_plugin().manifest
        assert manifest.lease_ttl_s is not None
        assert manifest.beat_timeout_s is not None
        assert manifest.lease_ttl_s >= manifest.beat_timeout_s


# --- harness wiring ---


class TestApiVerifierWiring:
    def test_manifest_declares_the_api_verifier(self) -> None:
        plugin = backend_engineer_plugin()
        assert any(sa.name == "api_verifier" for sa in plugin.manifest.subagents)

    def test_manifest_grants_spawn_subagent(self) -> None:
        plugin = backend_engineer_plugin()
        assert "spawn_subagent" in plugin.manifest.tools

    def test_manifest_grants_the_secret_scan_safety_tool(self) -> None:
        # The §09 safety floor: the engineer must be able to prove no hardcoded secrets before landing.
        plugin = backend_engineer_plugin()
        assert "secret_scan" in plugin.manifest.tools

    def test_verifier_tools_are_a_subset_of_the_parent(self) -> None:
        plugin = backend_engineer_plugin()
        parent_tools = set(plugin.manifest.tools)
        for tool in API_VERIFIER_SUBAGENT.tools:
            assert tool in parent_tools, f"{tool!r} not in the Backend Engineer's toolset"

    def test_beat_config_carries_the_subagent(self) -> None:
        config = role_beat_config(backend_engineer_plugin().manifest)
        assert "api_verifier" in {sa.name for sa in config.subagents}

    def test_projection_offers_the_verifier_at_runtime(self) -> None:
        config = role_beat_config(backend_engineer_plugin().manifest)
        result = _subagent_set(config)
        assert result is not None
        child = result.get("api_verifier")
        assert child is not None
        # The projection maps chorus tool names to dream's — run_command -> bash — and intersects with
        # the parent's live toolset, so the child carries the dream name here.
        assert "bash" in child.tools

    def test_api_verifier_is_strict_and_projects_strict(self) -> None:
        # DoD grader: malformed verdicts must fail closed, not fail-open with a warning.
        assert API_VERIFIER_SUBAGENT.strict is True
        assert API_VERIFIER_SUBAGENT.output_schema is not None
        config = role_beat_config(backend_engineer_plugin().manifest)
        result = _subagent_set(config)
        assert result is not None
        child = result.get("api_verifier")
        assert child is not None
        assert child.strict is True
        assert child.output_schema == API_VERIFIER_SUBAGENT.output_schema


class TestSubagentsCanLoadSkills:
    """The §06 subagents read the engineer's authored playbooks via the `skill` tool.

    The harness loads ONE ``skill_registry`` from Bex's ``skills_root`` and shares it with the inline
    child session, so a subagent that carries ``skill`` reaches the same playbooks as the parent —
    no per-subagent skills dir. These pin the grant + the projection + the shared source dir.
    """

    def test_both_subagents_carry_the_skill_tool(self) -> None:
        assert "skill" in TEST_AUTHOR_SUBAGENT.tools
        assert "skill" in API_VERIFIER_SUBAGENT.tools

    def test_skill_survives_projection_to_both_children(self) -> None:
        # `skill` is identity-mapped chorus->dream and Bex has it, so the narrower-wins intersection
        # keeps it on each projected child.
        config = role_beat_config(backend_engineer_plugin().manifest)
        result = _subagent_set(config)
        assert result is not None
        for name in ("test_author", "api_verifier"):
            child = result.get(name)
            assert child is not None
            assert "skill" in child.tools, f"{name} lost the skill tool in projection"

    def test_skill_registry_loads_from_the_employee_skills_dir(self) -> None:
        # The registry the child reads is built from the ENGINEER's skills/ dir — the same authored
        # playbooks Bex uses, not a separate subagent library.
        manifest = backend_engineer_plugin().manifest
        assert manifest.skills_root is not None
        registry, _shadows = load_skill_registry(project_dirs=[Path(manifest.skills_root)])
        available = {meta.name for meta in registry.list_meta()}
        assert {"structuring-any-service", "verifying-any-stack"} <= available

    def test_test_author_prompt_points_at_a_testing_playbook(self) -> None:
        assert "skill" in TEST_AUTHOR_SUBAGENT.description.lower()

    def test_test_author_exercises_repeated_state_changes_and_constraints(self) -> None:
        desc = TEST_AUTHOR_SUBAGENT.description.lower()
        assert "at least three sequential operations" in desc
        assert "uniqueness" in desc
        assert "transitional or placeholder state" in desc
