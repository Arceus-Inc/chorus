"""The Backend Engineer's brief must carry a craft bar (§08/§09): structure + clean code + a gate.

Bex's early services shipped as a flat pile of scripts with broad `except Exception`s and no lint/type
gate — green tests but poor code. The brief now demands a proper package layout, clean idiomatic code,
and a MECHANICAL quality gate (formatter/linter/type-checker over its own code, recorded as
test_evidence). These tests pin that intent so it can't silently regress.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus_employee.backend_engineer import BACKEND_ENGINEER_BRIEF, backend_engineer_plugin

pytestmark = pytest.mark.unit


class TestQualityGateWiring:
    def test_manifest_grants_the_code_quality_tool_and_skill_loader(self) -> None:
        tools = set(backend_engineer_plugin().manifest.tools)
        assert "code_quality" in tools
        assert "skill" in tools

    def test_manifest_carries_the_framework_agnostic_quality_skill(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert "verifying-any-stack" in manifest.skills
        assert manifest.skills_root is not None

    def test_the_verifying_any_stack_skill_file_exists(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert manifest.skills_root is not None
        skill = Path(manifest.skills_root) / "verifying-any-stack" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "code_quality" in body  # points at the tool
        assert "discover" in body  # framework-agnostic discovery, not a hardcoded table

    def test_brief_routes_the_quality_gate_through_the_tool_and_skill(self) -> None:
        brief = BACKEND_ENGINEER_BRIEF
        assert "code_quality" in brief
        assert "verifying-any-stack" in brief

    def test_brief_demands_all_three_quality_kinds_not_just_types(self) -> None:
        # The mechanical lever: format + lint + types are non-optional, tagged by kind.
        brief = BACKEND_ENGINEER_BRIEF
        assert "ALL THREE" in brief
        assert '"kind"' in brief  # each check is tagged with its gate kind


class TestStructureSkillWiring:
    def test_manifest_carries_the_structuring_skill(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert "structuring-any-service" in manifest.skills
        assert manifest.skills_root is not None

    def test_the_structuring_skill_file_exists(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert manifest.skills_root is not None
        skill = Path(manifest.skills_root) / "structuring-any-service" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "by domain" in body  # the #1 rule
        assert "inward" in body  # dependency direction

    def test_brief_routes_structure_through_the_skill_and_demands_by_domain(self) -> None:
        brief = BACKEND_ENGINEER_BRIEF
        assert "structuring-any-service" in brief
        assert "DOMAIN" in brief
        assert "INWARD" in brief


def test_brief_demands_a_package_layout_not_a_flat_dump() -> None:
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "package" in brief
    assert "flat" in brief  # "never a flat pile of scripts"


def test_brief_demands_layered_separation_of_concerns() -> None:
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "transport/http → service → data-access → domain" in brief
    assert "one reason to change" in brief


def test_brief_forbids_broad_exceptions_and_wants_full_typing() -> None:
    brief = BACKEND_ENGINEER_BRIEF
    assert "except Exception" in brief  # named as the thing NOT to do
    assert "type every function signature" in BACKEND_ENGINEER_BRIEF.lower()


def test_brief_requires_a_mechanical_lint_or_type_gate() -> None:
    # "clean code" must be proven, not eyeballed — a formatter/linter/type-checker over its own code,
    # recorded as a test_evidence gate.
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "linter" in brief or "ruff" in brief
    assert "test_evidence" in brief
    assert "red gate" in brief


def test_brief_keeps_the_landed_diff_clean_of_scratch_files() -> None:
    assert "no scratch" in BACKEND_ENGINEER_BRIEF.lower()


def test_brief_has_the_resume_reconcile_directive() -> None:
    # The cross-beat resumption protocol: keep a durable TODO.md via todo_write, read it FIRST and
    # reconcile intent (the checklist) against reality (git + tests), resume rather than restart.
    brief = BACKEND_ENGINEER_BRIEF
    assert "todo_write" in brief
    assert "TODO.md" in brief
    assert "resume" in brief.lower()


def test_brief_resume_trusts_green_artifacts_and_skips_to_the_missing_one() -> None:
    # Root cause of the stalled 4-domain run: on resume Bex re-verified already-green, artifact-backed
    # steps (re-ran api_verifier though api_verdict.json was already passed) and starved the terminal
    # steps (code_reviewer, secret_scan) of budget. The fix: a green durable artifact means DONE — do
    # not re-run it; jump to the FIRST checklist item whose artifact is still missing.
    brief = BACKEND_ENGINEER_BRIEF
    lower = brief.lower()
    assert "artifact" in lower
    assert "missing" in lower  # advance to the first MISSING artifact
    assert "do not re-run" in lower or "don't re-run" in lower or "do not redo" in lower


def test_brief_mandates_test_first_tdd_via_the_test_author() -> None:
    # TDD is not optional: the test_author writes the FAILING test FIRST (RED), before the engineer
    # implements — delegation is mandatory, not "for non-trivial behaviour".
    brief = BACKEND_ENGINEER_BRIEF
    assert "test_author" in brief
    assert "RED" in brief  # sees the test fail first
    lower = brief.lower()
    assert (
        "test-first" in lower or "before you implement" in lower or "before implementing" in lower
    )
    # the old optional phrasing is gone — delegation is required
    assert "for non-trivial behaviour, delegate" not in lower


def test_brief_gates_done_on_the_subagent_artifacts() -> None:
    # The compel: done requires the durable proofs the independent subagents write, not the model's
    # word — test_plan.json (tests authored + seen RED) and api_verdict.json (the service booted).
    brief = BACKEND_ENGINEER_BRIEF
    assert "test_plan.json" in brief
    assert "api_verdict.json" in brief


def test_brief_mandates_the_code_reviewer_red_team() -> None:
    # The §06 verification swarm's third leg: an independent red-team of the diff for the prod-failure
    # classes tests miss — gated on a durable review_verdict.json (cleared).
    brief = BACKEND_ENGINEER_BRIEF
    assert "code_reviewer" in brief
    assert "review_verdict.json" in brief
    lower = brief.lower()
    assert "red-team" in lower or "red team" in lower
    # names at least one prod-failure class it must hunt
    assert "authz" in lower or "authorization" in lower or "n+1" in lower


def test_dod_rubric_gates_on_the_cleared_review() -> None:
    from chorus_employee.backend_engineer import backend_engineer_dod

    rubric = backend_engineer_dod("build a service").rubric()
    assert "review_verdict.json" in rubric
    assert "cleared" in rubric.lower()


def test_dod_rubric_makes_the_reviewer_gate_on_the_tdd_artifacts() -> None:
    # reviewed_build's only deterministic floor is the reviewer-discovered verify_command the kernel
    # runs. The rubric compels the reviewer to fold the artifact checks into that command, so "done"
    # mechanically requires the RED-first test_plan.json + (for a service) api_verdict.json.
    from chorus.outcomes import DoDKind
    from chorus_employee.backend_engineer import backend_engineer_dod

    dod = backend_engineer_dod("build a small commerce API")
    assert dod.kind is DoDKind.REVIEWED_BUILD
    rubric = dod.rubric()
    assert "test_plan.json" in rubric
    assert "api_verdict.json" in rubric
    assert "verify_command" in rubric  # instruct the reviewer to assert them in the run command
    assert "red_evidence" in rubric.lower() or "red" in rubric.lower()


def test_dod_rubric_mechanically_requires_the_durable_evidence_floor() -> None:
    # spec §10: "it was tested" must be a file on disk, not a claim. The reviewer-discovered
    # verify_command must include a green test_evidence/manifest.json check — the durable evidence
    # floor the kernel greps, not something only the brief's prose asks for.
    from chorus_employee.backend_engineer import backend_engineer_dod

    rubric = backend_engineer_dod("build a service").rubric()
    assert "test_evidence/manifest.json" in rubric
    assert '"verdict": "pass"' in rubric
