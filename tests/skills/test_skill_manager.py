"""SkillManager — Hermes-shaped actions, Chorus SkillStore, Lattice validate-only.

Harness observation contract on every result:
  status · summary · next_actions · artifacts · (error → root_cause · retry · stop)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus.skills import SkillStore
from chorus.skills.manager import SkillManager, SkillObservation

pytestmark = pytest.mark.unit

_EVOLVE_BODY = (
    "## Before patching HTTP clients\n\n"
    "1. Call `get_run(run_id)` for each cited beat and recall the failure shape.\n"
    "2. Classify transient (429/503) versus logic error before editing.\n"
    "3. Only then edit `src/api/client.py`.\n\n"
    "## Pitfalls\n"
    "- Patching without reading prior beat prose repeats the same mistake.\n\n"
    "## Verification\n"
    "- `test_evidence` passes after the patch.\n"
)

_CREATE_BODY = (
    "## When to Use\n"
    "Use when introducing a new HTTP client retry playbook for a service class "
    "that must survive transient upstream failures without masking logic bugs.\n\n"
    "## Procedure\n"
    "1. Read prior beats with get_run and classify the failure shape.\n"
    "2. Distinguish transient (429/503) from application errors before editing.\n"
    "3. Patch the client with bounded retries, exponential backoff, and a cap.\n"
    "4. Document the policy in README and verify with integration tests.\n"
    "5. Prefer evolving structuring-any-service when the lesson is structural.\n\n"
    "## Pitfalls\n"
    "- Do not invent status codes that the upstream never returns.\n"
    "- Do not CREATE a micro-skill for a one-line retry tweak.\n"
    "- Do not promote session diary notes into this playbook.\n\n"
    "## Verification\n"
    "- Integration tests pass and lattice_context still holds the numeric policy.\n"
)


class _Ep:
    def __init__(self, run_id: str, outcome: str = "done") -> None:
        self.run_id = run_id
        self.employee_id = "bex"
        self.outcome = outcome


def _mgr(tmp_path: Path, *, canonical: Path | None = None) -> SkillManager:
    store = SkillStore(tmp_path / "skills")
    if canonical is None:
        canonical = tmp_path / "canonical"
        skill = canonical / "structuring-any-service"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: structuring-any-service\n"
            "description: structure services\n"
            "when_to_use: before writing a service\n"
            "---\n\n# Structuring\n\nCanonical body.\n",
            encoding="utf-8",
        )
    return SkillManager(
        store,
        employee_id="bex",
        canonical_skills_root=canonical,
        episodes=(_Ep("r0"), _Ep("r1")),
    )


def test_evolve_appends_section_and_returns_harness_obs(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    try:
        obs = mgr.apply(
            action="evolve",
            name="structuring-any-service",
            section="Before patching HTTP clients",
            content=_EVOLVE_BODY,
            source_run_ids=["r0", "r1"],
        )
        assert obs.status == "success"
        assert obs.artifacts["revision_no"] == 1
        assert obs.artifacts["skill"] == "structuring-any-service"
        assert obs.next_actions
        head = mgr.store.head(obs.artifacts["skill_id"])
        assert head is not None
        text = head.inventory()[0]["content"]
        assert "Before patching HTTP clients" in text
        assert "when_to_use: before writing a service" in text
    finally:
        mgr.close()


def test_patch_find_replace_bumps_revision(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    try:
        first = mgr.apply(
            action="evolve",
            name="structuring-any-service",
            section="Before patching HTTP clients",
            content=_EVOLVE_BODY,
            source_run_ids=["r0", "r1"],
        )
        obs = mgr.apply(
            action="patch",
            name="structuring-any-service",
            old_string="Classify transient (429/503)",
            new_string="Classify transient (429/503/504)",
        )
        assert obs.status == "success"
        assert obs.artifacts["revision_no"] == 2
        assert first.artifacts["revision_no"] == 1
        text = mgr.store.head(obs.artifacts["skill_id"]).inventory()[0]["content"]
        assert "429/503/504" in text
    finally:
        mgr.close()


def test_patch_miss_returns_recovery_contract(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    try:
        mgr.apply(
            action="evolve",
            name="structuring-any-service",
            section="Before patching HTTP clients",
            content=_EVOLVE_BODY,
            source_run_ids=["r0", "r1"],
        )
        obs = mgr.apply(
            action="patch",
            name="structuring-any-service",
            old_string="this string does not exist anywhere",
            new_string="noop",
        )
        assert obs.status == "error"
        assert obs.root_cause
        assert obs.retry
        assert obs.stop
        assert obs.next_actions
    finally:
        mgr.close()


def test_diary_evolve_rejected(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    try:
        obs = mgr.apply(
            action="evolve",
            name="structuring-any-service",
            section="Notes",
            content=(
                "we found 86 calls today in this session on 2026-07-11 and fixed them. "
                + ("x" * 180)
            ),
            source_run_ids=["r0"],
        )
        assert obs.status == "error"
        assert "diary" in (obs.root_cause or obs.summary).lower() or "diary" in obs.summary.lower()
    finally:
        mgr.close()


def test_create_class_level_skill(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    try:
        obs = mgr.apply(
            action="create",
            name="http-retry-playbook",
            content=(
                "---\n"
                "name: http-retry-playbook\n"
                'description: "HTTP retry playbook for service clients"\n'
                'when_to_use: "when adding retries to an HTTP client"\n'
                "---\n\n"
                "# HTTP Retry Playbook\n\n" + _CREATE_BODY
            ),
            source_run_ids=["r0", "r1"],
        )
        assert obs.status == "success", obs.summary
        assert obs.artifacts["revision_no"] == 1
        assert mgr.store.get_by_slug("bex", "http-retry-playbook") is not None
    finally:
        mgr.close()


def test_observation_shape_keys(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    try:
        obs = mgr.apply(
            action="evolve",
            name="structuring-any-service",
            section="Before patching HTTP clients",
            content=_EVOLVE_BODY,
            source_run_ids=["r0", "r1"],
        )
        d = obs.as_dict()
        for key in ("status", "summary", "next_actions", "artifacts"):
            assert key in d
        assert d["status"] == "success"
    finally:
        mgr.close()


def test_SkillObservation_error_fields() -> None:
    obs = SkillObservation.error(
        summary="failed",
        root_cause="missing skill",
        retry="call view to list skills",
        stop="after 2 misses stop inventing slugs",
        next_actions=["skill_manage(action='view')"],
    )
    assert obs.status == "error"
    assert obs.as_dict()["root_cause"] == "missing skill"
