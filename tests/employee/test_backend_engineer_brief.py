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

    def test_all_three_quality_kinds_are_machine_enforced_not_prose(self) -> None:
        # Per docs/plans/2026-07-18-hooks-and-briefs-research.md §B the "ALL THREE kinds" rule left
        # the brief: CodeQualityInput's validator refuses a partial report, and the tool description
        # carries the worked example — the gate holds, prose would only decay.
        from pydantic import ValidationError

        from chorus_tools._code_quality import CodeQualityInput, CodeQualityTool

        with pytest.raises(ValidationError, match="all three gate kinds"):
            CodeQualityInput.model_validate(
                {"checks": [{"name": "types", "kind": "types", "command": "mypy ."}]}
            )
        assert "all three gate kinds" in CodeQualityTool.description


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


def test_layered_separation_of_concerns_lives_in_the_structuring_skill() -> None:
    # Per docs/plans/2026-07-18-hooks-and-briefs-research.md §B the layering procedure moved from
    # the brief into its natural owner, the structuring-any-service skill; the brief keeps only the
    # by-DOMAIN / INWARD judgment pointer (pinned above).
    manifest = backend_engineer_plugin().manifest
    assert manifest.skills_root is not None
    body = (
        (Path(manifest.skills_root) / "structuring-any-service" / "SKILL.md")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "transport" in body and "inward" in body
    assert "one reason to change" in body


def test_clean_code_craft_lives_in_the_structuring_skill() -> None:
    # Per docs/plans/2026-07-18-hooks-and-briefs-research.md §B the clean-code craft detail (typing,
    # specific exceptions, small functions) moved from the brief into structuring-any-service.
    manifest = backend_engineer_plugin().manifest
    assert manifest.skills_root is not None
    body = (
        (Path(manifest.skills_root) / "structuring-any-service" / "SKILL.md")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "except exception" in body  # named as the thing NOT to do
    assert "type every function signature" in body


def test_brief_requires_a_mechanical_lint_or_type_gate() -> None:
    # "clean code" must be proven, not eyeballed — a formatter/linter/type-checker over its own code,
    # recorded as a test_evidence gate.
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "linter" in brief or "ruff" in brief
    assert "test_evidence" in brief
    assert "red gate" in brief


def test_brief_keeps_the_landed_diff_clean_of_scratch_files() -> None:
    assert "no scratch" in BACKEND_ENGINEER_BRIEF.lower()


def test_brief_keeps_generated_runtime_state_out_of_the_diff() -> None:
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "generated runtime state" in brief
    assert "database" in brief
    assert "cache" in brief
    assert "git status" in brief


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


def test_brief_implement_first_matrix_wins() -> None:
    brief = BACKEND_ENGINEER_BRIEF
    lower = brief.lower()
    assert "tool > skill > spawn" in lower
    assert "just implement yourself" in lower
    assert "do not spawn to wrap a single tool" in lower or "spawn to wrap a single tool" in lower


def test_brief_routes_tdd_through_skill_not_spawn() -> None:
    brief = BACKEND_ENGINEER_BRIEF
    assert "test-driven-development" in brief
    assert "RED→GREEN→REFACTOR" in brief or "RED" in brief
    lower = brief.lower()
    assert "prefer `test-driven-development`" in lower or "prefer test-driven-development" in lower
    assert "delegate the failing tests via" not in lower


def test_manifest_offers_tdd_and_honeycomb_skills() -> None:
    manifest = backend_engineer_plugin().manifest
    assert "test-driven-development" in manifest.skills
    assert "testing-honeycomb-strategy" in manifest.skills
    assert manifest.skills_root is not None
    tdd = Path(manifest.skills_root) / "test-driven-development" / "SKILL.md"
    assert tdd.is_file()
    body = tdd.read_text(encoding="utf-8").lower()
    assert "no production code without a failing test first" in body
    assert "tool > skill > spawn" in body
    assert "jobqueue" not in body and "queue.py" not in body
    assert "explicit task filename wins" in body
    assert "selects that exact resource" in body


def test_brief_does_not_mandate_test_author_before_implement() -> None:
    lower = BACKEND_ENGINEER_BRIEF.lower()
    assert "delegate the failing tests via" not in lower
    assert "only then implement" not in lower
    assert "code's author is never the sole author" not in lower


def test_brief_does_not_require_terminal_code_reviewer() -> None:
    lower = BACKEND_ENGINEER_BRIEF.lower()
    assert "every initial `todo.md` checklist ends" not in lower
    assert "spawn `code_reviewer`" not in lower


def test_brief_spawn_when_not_language() -> None:
    lower = BACKEND_ENGINEER_BRIEF.lower()
    assert "re-delegate the whole ticket" in lower or "whole ticket" in lower
    assert "trivial" in lower or "isolation" in lower


def test_brief_api_verifier_only_for_running_service() -> None:
    brief = BACKEND_ENGINEER_BRIEF
    assert "api_verifier" in brief
    assert "running service or API" in brief


def test_brief_optional_specialist_evidence_paths() -> None:
    """Forge paths named; not mandatory swarm ritual."""
    brief = BACKEND_ENGINEER_BRIEF
    assert "test_plan.json" in brief
    assert "review_verdict.json" in brief
    assert "never write that specialist" in brief.lower() or "must not forge" in brief.lower()


def test_dod_is_a_self_judged_agent_review_without_evidence_file_demands() -> None:
    # Operator decision (2026-07-18): employees verify their own work — no kernel evidence machinery.
    # The rubric judges substance the employee can self-check in-beat (tests pass when run, diff
    # implements the contract, inputs validated, no secrets) and demands NO evidence-bundle files.
    from chorus.outcomes import DoDKind
    from chorus_employee.backend_engineer import backend_engineer_dod

    dod = backend_engineer_dod("build a small commerce API")
    assert dod.kind is DoDKind.AGENT_REVIEW
    rubric = dod.rubric()
    assert "test" in rubric.lower() and "secret" in rubric.lower()
    for evidence_file in (
        "test_evidence/manifest.json",
        "test_evidence/red.json",
        "test_plan.json",
        "review_verdict.json",
        "api_verdict.json",
    ):
        assert evidence_file not in rubric


def test_dod_rubric_requires_tests_to_actually_run() -> None:
    # Operator decision (2026-07-18): the durable evidence-file floor is gone; the rubric instead
    # binds the in-beat evaluator to substance it can check itself — the tests exist and pass when
    # actually run, never on the model's word.
    from chorus_employee.backend_engineer import backend_engineer_dod

    rubric = backend_engineer_dod("build a service").rubric().lower()
    assert "pass" in rubric and "run" in rubric
    assert "test_evidence/manifest.json" not in rubric


def test_brief_fits_the_lean_token_budget() -> None:
    """The brief stays under ~1050 tokens (words * 4/3 heuristic).

    docs/plans/2026-07-18-hooks-and-briefs-research.md §B (podium repo): target <~600 tokens for
    character/judgment; hard budget raised to 1050 to leave room for the Hermes-style tool-choice
    matrix (S0 #10) — action-space teaching stays in the invariant brief, not in skills.
    """
    assert len(BACKEND_ENGINEER_BRIEF.split()) * 4 / 3 <= 1050


def test_brief_keeps_the_anatomy_essentials() -> None:
    """Identity survives the diet: specialists named, manager escalation, deliverable class."""
    brief = BACKEND_ENGINEER_BRIEF
    for subagent in ("code_reviewer", "api_verifier", "generalPurpose"):
        assert subagent in brief, subagent
    assert "manager" in brief.lower()
    assert "PR" in brief
    assert "test_evidence" in brief


def test_brief_requires_a_useful_final_handoff() -> None:
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "what changed" in brief
    assert "verification commands and results" in brief
    assert "remaining caveats" in brief


def test_brief_requires_adversarial_semantic_review() -> None:
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "green authored tests as necessary but insufficient" in brief
    assert "public state transition" in brief
    assert "adversarial" in brief
    assert "identifier-bearing operation" in brief
    assert "another eligible resource exists" in brief


def test_brief_requires_review_defects_to_reopen_green_work() -> None:
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "needs-changes" in brief
    assert "reopens named items" in brief
    assert "before rerunning evidence" in brief


def test_brief_preserves_required_paths() -> None:
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "required paths are public api" in brief
    assert "never rename them" in brief
