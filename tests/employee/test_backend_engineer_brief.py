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


def test_brief_initial_checklist_cannot_omit_independent_review() -> None:
    brief = BACKEND_ENGINEER_BRIEF
    assert "every initial `todo.md`" in brief.lower()
    assert "spawn `code_reviewer`" in brief
    assert "do not return your final answer" in brief.lower()
    assert "review_verdict.json" in brief


def test_brief_invalidates_review_after_every_later_mutation() -> None:
    lower = BACKEND_ENGINEER_BRIEF.lower()
    assert "every git-visible mutation after review invalidates that review" in lower
    assert "correction sprint" in lower
    assert "rerun the configured gates" in lower
    assert "spawn `code_reviewer` again" in lower


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
    assert "test_red" in lower
    # Per docs/plans/2026-07-18-hooks-and-briefs-research.md §B the RED-chronology prohibitions
    # ("without writing a production file", "do not edit those test files after RED", the test-hash
    # warning) left the brief: the test_red/test_evidence tools prove the chronology. Prose would
    # only decay.
    assert "quote the exact assigned behavior" in lower
    assert "never ask it to infer" in lower


def test_brief_gates_done_on_the_subagent_artifacts() -> None:
    # The compel: done requires the durable proofs the independent subagents write, not the model's
    # word — test_plan.json (tests authored + seen RED) and api_verdict.json (the service booted).
    brief = BACKEND_ENGINEER_BRIEF
    assert "test_plan.json" in brief
    assert "api_verdict.json" in brief
    assert "`api_verdict.json` only when the deliverable is a running service or API" in brief


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
    """The brief stays under ~900 tokens (words * 4/3 heuristic).

    docs/plans/2026-07-18-hooks-and-briefs-research.md §B (podium repo): target <~600 tokens, hard
    budget 900 — 250-375-token instruction blocks beat 1500+ on tool selection; briefs carry
    character and judgment, gates carry law.
    """
    assert len(BACKEND_ENGINEER_BRIEF.split()) * 4 / 3 <= 900


def test_brief_keeps_the_anatomy_essentials() -> None:
    """Identity survives the diet: subagents by name, manager escalation, deliverable class."""
    brief = BACKEND_ENGINEER_BRIEF
    for subagent in ("test_author", "api_verifier", "code_reviewer"):
        assert subagent in brief, subagent
    assert "manager" in brief.lower()  # escalate-to-manager communication norm
    assert "PR" in brief  # the deliverable artifact class it lands
    assert "test_evidence" in brief  # the durable evidence bundle it leaves
