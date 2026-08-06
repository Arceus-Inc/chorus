"""PM — Slice 0: plugin assembly, the grounding-floor DoD, and the doc lander (pm design doc §01-§15).

The PM's signature elevation over the thin triple is its **grounding floor** (design doc §01/§09/§10):
a decision that states no decision or cites no evidence never clears "done". With the Decision OS the
floor is a deterministic ``Verifier.command`` over the recorded ``decision.json`` (plus the plan doc) —
the same move the Marketer made (a reversible artifact lands on an objective check, not a stochastic
reviewer). These tests pin the floor's shape and prove it gates a grounded decision in and a weak one out.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import ClassVar

import pytest

from chorus.ledger import Ledger, Task, TaskStatus
from chorus.outcomes import ArtifactType, DoDKind
from chorus.roles import default_roles, role_beat_config
from chorus.roles._manifest import Isolation, MemoryScope, PermissionMode, SandboxTier
from chorus.testing import uid
from chorus.workspace import CompanyWorkspace
from chorus_employee import default_landers
from chorus_employee.pm import (
    PM_BRIEF,
    PM_PLAN_DOC,
    PM_ROUTINES,
    pm_lander,
    pm_plugin,
)
from chorus_employee.pm._decision import CONFIDENCE_FLOOR

pytestmark = pytest.mark.integration


def _task(assignee: str | None) -> Task:
    return Task(
        id=uid("decide-brief"),
        intent="decide whether to build presence indicators next",
        status=TaskStatus.IN_PROGRESS,
        assignee_employee_id=assignee,
    )


# --- Plugin assembly ---


class TestPmPlugin:
    def test_plugin_name_and_outcome_kind(self) -> None:
        plugin = pm_plugin()
        assert plugin.name == "pm"
        assert plugin.outcome_kind == "doc"

    def test_manifest_system_prompt_is_the_brief(self) -> None:
        assert pm_plugin().manifest.system_prompt == PM_BRIEF

    def test_brief_demands_a_decision_and_a_cited_source(self) -> None:
        # §01/§10: the floor's whole point — a decision, grounded in evidence. The brief must tell the
        # PM to write the structure the deterministic floor checks: a Decision section + ≥1 source.
        assert "## Decision" in PM_BRIEF
        assert "source" in PM_BRIEF.lower()
        assert PM_PLAN_DOC in PM_BRIEF

    def test_manifest_tools_are_read_write_only(self) -> None:
        manifest = pm_plugin().manifest
        assert "read_file" in manifest.tools
        assert "write_file" in manifest.tools
        assert "run_command" not in manifest.tools
        assert "git" not in manifest.tools

    def test_manifest_posture(self) -> None:
        manifest = pm_plugin().manifest
        assert manifest.permission_mode == PermissionMode.ACCEPT_EDITS
        assert manifest.isolation == Isolation.WORKTREE
        # REPO_WRITE_NET: the PM writes its plan in-worktree AND may reach the net through the
        # allowlist a registered tool declares (browser_run/browser_run → api.chromium-cdp.com). No commands.
        assert manifest.sandbox == SandboxTier.REPO_WRITE_NET
        assert manifest.memory_scope == MemoryScope.PROJECT

    def test_declares_the_weekly_routine(self) -> None:
        assert pm_plugin().declared_routines == PM_ROUTINES

    def test_pm_is_registered_in_the_default_workforce(self) -> None:
        assert "pm" in {plugin.name for plugin in default_roles()}


# --- Web research: the PM can gather its own cited evidence (design doc §07/§08/§10) ---


class TestPmWebResearch:
    """The grounding floor demands a source; §08's shelf lets the PM fetch one inline.

    §10's confidence policy is explicit — below the floor, *acquire evidence* rather than hedge. This
    slice gives the PM the same Chromium CDP-backed web reach the Marketer holds: search + extract, egress
    allowlisted by the net sandbox tier, with a widened beat so a live sweep isn't reaped mid-call.
    """

    def test_manifest_grants_browser_run_and_extract(self) -> None:
        tools = pm_plugin().manifest.tools
        assert "browser_run" in tools  # §08 shelf: Chromium CDP-backed search
        assert "browser_run" in tools  # §08 shelf: fetch + clean-read a source to ground a claim

    def test_web_reach_needs_the_net_sandbox_tier(self) -> None:
        # Egress is only reachable under REPO_WRITE_NET; without it the allowlisted call is blocked.
        assert pm_plugin().manifest.sandbox == SandboxTier.REPO_WRITE_NET

    def test_manifest_grants_product_state_read(self) -> None:
        # §03 input ①: the PM grounds a decision on product state, not only the web — repo (feasibility /
        # what's shipped) + the warehouse (usage/funnel metrics). Both are tier-0, read-only.
        tools = pm_plugin().manifest.tools
        assert "repo_search" in tools
        assert "warehouse_query" in tools

    def test_product_state_tools_reach_the_beat_config(self) -> None:
        # The manifest is the single source; role_beat_config projects it into what the factory registers.
        config = role_beat_config(pm_plugin().manifest)
        assert "repo_search" in config.tools
        assert "warehouse_query" in config.tools

    def test_brief_directs_reading_product_state(self) -> None:
        # The reach is only useful if the PM consults it — the brief must name the internal surfaces.
        assert "repo_search" in PM_BRIEF and "warehouse_query" in PM_BRIEF

    def test_brief_points_the_pm_at_research_when_evidence_is_thin(self) -> None:
        # §10 confidence policy: weak evidence triggers acquisition, not a hedge.
        assert "browser_run" in PM_BRIEF

    def test_manifest_widens_the_beat_for_a_live_research_sweep(self) -> None:
        # A web sweep blocks the beat in one call; org defaults (90s beat / 300s lease) would reap it.
        manifest = pm_plugin().manifest
        assert manifest.beat_timeout_s is not None and manifest.beat_timeout_s >= 300.0
        assert manifest.lease_ttl_s is not None and manifest.lease_ttl_s >= manifest.beat_timeout_s


class TestPmSkillLibrary:
    """§08: the PM's competence is a deep skill library, not more verbs. Slice 1 wires the `skill` tool
    and authors the Decision-core group — the playbooks that ARE the Decision OS method (evidence →
    options → decision → recommendation). Later slices add the Discovery / Prioritization / … groups.
    """

    _DECISION_CORE: ClassVar[frozenset[str]] = frozenset(
        {"evidence-brief", "options-set-generator", "decision-record", "recommendation-canvas"}
    )

    def test_manifest_declares_the_decision_core_skills(self) -> None:
        manifest = pm_plugin().manifest
        assert self._DECISION_CORE <= set(manifest.skills)
        assert manifest.skills_root is not None
        assert "skill" in manifest.tools  # the tool that loads a skill body on demand

    def test_declared_skills_resolve_to_valid_skill_files(self) -> None:
        """Every declared skill is a discoverable SKILL.md with valid frontmatter (no dangling names)."""
        from pathlib import Path

        from dream.skills import load_skill_registry

        manifest = pm_plugin().manifest
        assert manifest.skills_root is not None
        registry, _shadows = load_skill_registry(project_dirs=[Path(manifest.skills_root)])
        discovered = {meta.name for meta in registry.list_meta()}
        assert set(manifest.skills) <= discovered

    def test_brief_promotes_the_skill_library(self) -> None:
        # The reach is useless if the PM doesn't reach for it — the brief must point at `skill`.
        assert "skill" in PM_BRIEF

    def test_beat_config_carries_the_widened_timeouts(self) -> None:
        manifest = pm_plugin().manifest
        config = role_beat_config(manifest)
        assert config.beat_timeout_s == manifest.beat_timeout_s
        assert config.lease_ttl_s == manifest.lease_ttl_s


# --- DoD: the grounding floor ---


class TestPmGroundingFloorDoD:
    """The floor gates on the RECORDED decision (§10): decision.json states an option, meets the
    confidence floor, and cites >= 1 source — defense-in-depth over the record_decision tool's own gate.
    """

    def test_dod_is_a_deterministic_command(self) -> None:
        # The elevation: a reversible plan lands on an objective floor, not a stochastic AgentReview.
        verifier = pm_plugin().dod_generator("decide the thing")
        assert verifier.kind == DoDKind.COMMAND

    def test_dod_artifact_class_is_spec(self) -> None:
        assert pm_plugin().dod_generator("decide the thing").artifact_class == "spec"

    def test_floor_command_checks_plan_decision_and_confidence(self) -> None:
        command = " ".join(
            step.command for step in pm_plugin().dod_generator("x").verification_steps()
        )
        assert PM_PLAN_DOC in command  # the human-readable deliverable must be present
        assert "decision.json" in command  # a decision was recorded
        assert str(CONFIDENCE_FLOOR) in command  # the confidence floor is enforced

    # --- the floor actually gates (deterministic proof, run in a temp worktree) ---

    def _grounded(self) -> dict[str, object]:
        return {
            "option": "build presence indicators",
            "confidence": 0.82,
            "claims": [{"text": "x", "source_url": "https://arceus.sh/metrics", "confidence": 0.9}],
        }

    def _floor_passes(
        self, tmp_path: Path, decision: dict[str, object] | None, *, plan: str = "# Plan\n"
    ) -> bool:
        (tmp_path / PM_PLAN_DOC).write_text(plan, encoding="utf-8")
        if decision is not None:
            (tmp_path / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
        command = " ".join(
            step.command for step in pm_plugin().dod_generator("x").verification_steps()
        )
        return (
            subprocess.run(command, shell=True, cwd=tmp_path, capture_output=True).returncode == 0
        )

    def test_floor_passes_a_grounded_decision(self, tmp_path: Path) -> None:
        assert self._floor_passes(tmp_path, self._grounded()) is True

    def test_floor_rejects_low_confidence(self, tmp_path: Path) -> None:
        assert self._floor_passes(tmp_path, self._grounded() | {"confidence": 0.4}) is False

    def test_floor_rejects_no_cited_claim(self, tmp_path: Path) -> None:
        assert self._floor_passes(tmp_path, self._grounded() | {"claims": []}) is False

    def test_floor_rejects_a_claim_missing_its_source(self, tmp_path: Path) -> None:
        decision = self._grounded() | {"claims": [{"text": "x", "confidence": 0.9}]}
        assert self._floor_passes(tmp_path, decision) is False

    def test_floor_rejects_a_missing_decision(self, tmp_path: Path) -> None:
        assert self._floor_passes(tmp_path, None) is False

    def test_floor_rejects_a_missing_plan(self, tmp_path: Path) -> None:
        # decision.json present but no plan.md — the human-readable deliverable is still required.
        (tmp_path / "decision.json").write_text(json.dumps(self._grounded()), encoding="utf-8")
        command = " ".join(
            step.command for step in pm_plugin().dod_generator("x").verification_steps()
        )
        assert (
            subprocess.run(command, shell=True, cwd=tmp_path, capture_output=True).returncode != 0
        )


# --- Lander ---


class TestPmLander:
    def test_lander_snapshots_the_plan_doc(self, tmp_path: Path) -> None:
        workspace = CompanyWorkspace(tmp_path / "acme")
        worktree = workspace.worktree_for("pat")
        (worktree.path / PM_PLAN_DOC).write_text(
            "# Plan\n\n## Decision\nShip it. Source: https://x\n", encoding="utf-8"
        )

        artifact = asyncio.run(pm_lander(tmp_path / "acme").land(_task("pat"), None))

        assert artifact.type is ArtifactType.DOC and artifact.is_primary is True
        assert artifact.resource_ref["kind"] == "plan_doc"
        assert artifact.resource_ref["doc"] == PM_PLAN_DOC
        assert artifact.resource_ref["present"] is True
        assert artifact.resource_ref["branch"] == "chorus/pat"
        assert artifact.resource_ref["commit"]

    def test_lander_rederives_decision_json_from_the_ledger(
        self, ledger: Ledger, tmp_path: Path
    ) -> None:
        """At landing, decision.json is re-derived from the ledger — repairing a model clobber.

        The tool mirrors the recorded decision mid-beat, but the model can still ``write_file`` a
        divergent decision.json afterward (seen in the live web e2e). The lander overwrites it with the
        canonical ledger row so the landed decision.json, the ledger, and the sources.json packet agree.
        """
        from chorus.lifecycle._capability import CapabilityService, ClaimDraft

        CapabilityService(ledger).record_decision(
            task_id=uid("decide-brief"),
            revision="r1",
            option="build presence indicators",
            rationale="run opacity is the top complaint",
            confidence=0.82,
            outcome_metric="'stuck' tickets drop 30%",
            revisit_trigger="if flat in 4 weeks, reopen",
            rejected=[],
            claims=[
                ClaimDraft(text="p", source_url="https://a", confidence=0.9),
                ClaimDraft(text="q", source_url="https://b", confidence=0.8),
            ],
        )
        workspace = CompanyWorkspace(tmp_path / "acme")
        worktree = workspace.worktree_for("pat")
        (worktree.path / PM_PLAN_DOC).write_text(
            "# Plan\n\n## Decision\nShip it. Source: https://a\n", encoding="utf-8"
        )
        # The model clobbered decision.json with a divergent hand-written version.
        (worktree.path / "decision.json").write_text(
            json.dumps(
                {
                    "option": "build a run timeline instead",
                    "confidence": 0.9,
                    "claims": [{"text": "z", "source_url": "https://z", "confidence": 0.9}],
                }
            ),
            encoding="utf-8",
        )

        asyncio.run(pm_lander(tmp_path / "acme", ledger=ledger).land(_task("pat"), None))

        mirror = json.loads((worktree.path / "decision.json").read_text(encoding="utf-8"))
        assert mirror["option"] == "build presence indicators"  # ledger, not the clobber
        assert {c["source_url"] for c in mirror["claims"]} == {"https://a", "https://b"}
        assert mirror["decision_id"]  # full canonical shape, not the model's partial file

    def test_lander_records_a_missing_doc_as_absent(self, tmp_path: Path) -> None:
        workspace = CompanyWorkspace(tmp_path / "acme")
        workspace.worktree_for("pat")

        artifact = asyncio.run(pm_lander(tmp_path / "acme").land(_task("pat"), None))

        assert artifact.resource_ref["present"] is False

    def test_lander_requires_an_assignee(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            asyncio.run(pm_lander(tmp_path / "acme").land(_task(None), None))

    def test_default_landers_registers_the_doc_lander(self, ledger: Ledger, tmp_path: Path) -> None:
        registry = default_landers(tmp_path, ledger=ledger)
        assert registry.get("doc") is not None
