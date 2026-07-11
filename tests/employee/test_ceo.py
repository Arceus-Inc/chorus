"""The CEO employee config — a complete dream harness, every component declared.

These tests pin the CEO as an executive role that **reads the company's state and writes a decisive
directive** — and that its authority stays narrow: no ``git``, no data/spend tools. They also assert the
CEO the kernel registers by default is exactly the one defined here (single source — no drift).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus.outcomes import DoDKind, Verifier
from chorus.roles import default_roles, role_beat_config
from chorus_employee import default_employees
from chorus_employee.ceo import ActionClass, ceo_plugin, classify_action

pytestmark = pytest.mark.unit


def test_ceo_declares_its_executive_toolset() -> None:
    manifest = ceo_plugin().manifest
    # Read the state, gather external context, write the directive, keep working notes.
    assert manifest.tools == (
        "read_file",
        "write_file",
        "run_command",
        "repo_search",
        "web_search",
        "web_extract",
        "read_offloaded",
        "skill",
        "memory_search",
        "memory_get",
        "working_memory_read",
        "working_memory_write",
        "working_memory_append",
    )
    assert manifest.permission_mode.value == "acceptEdits"
    assert manifest.memory_scope.value == "project"
    assert manifest.system_prompt  # a real operating brief, not a placeholder


def test_ceo_authority_stays_narrow() -> None:
    """The CEO governs — it reads the world and writes only its worktree; it does not crunch or spend."""
    manifest = ceo_plugin().manifest
    assert "git" not in manifest.tools  # the lander commits the directive, never the model
    assert "warehouse_query" not in manifest.tools  # not a data cruncher
    assert "notebook_run" not in manifest.tools
    assert manifest.working_memory is True
    assert manifest.max_turns >= 8  # a governance review is multi-step
    assert manifest.max_sprints > 1
    assert manifest.model is None  # uses the deployment model the composition root supplies
    assert manifest.mcp is False and manifest.plugins is False


def test_ceo_runs_in_an_isolated_worktree_sandbox() -> None:
    manifest = ceo_plugin().manifest
    assert manifest.isolation.value == "worktree"
    assert manifest.sandbox.value == "unrestricted"


def test_ceo_projects_to_a_beat_config_carrying_the_scalars() -> None:
    config = role_beat_config(ceo_plugin().manifest)
    assert "write_file" in config.tools and "skill" in config.tools
    assert "git" not in config.tools
    assert config.permission_mode == "acceptEdits"
    assert config.working_memory is True
    assert config.max_sprints > 1
    assert config.sandbox == "unrestricted"


def test_ceo_ships_its_dod_and_outcome() -> None:
    plugin = ceo_plugin()
    assert plugin.name == "ceo"
    assert plugin.outcome_kind == "directive"
    verifier = plugin.dod_generator("review the company and decide where to focus next quarter")
    assert isinstance(verifier, Verifier)
    assert verifier.kind is DoDKind.AGENT_REVIEW  # a directive is judged for executive quality
    assert verifier.rubric()


def test_ceo_commit_beat_crosses_the_human_gate() -> None:
    """An irreversible commitment is a governance gate a person signs, not a quality gate."""
    verifier = ceo_plugin().dod_generator("spend $50k on a paid acquisition campaign")
    assert verifier.kind is DoDKind.HUMAN_APPROVAL


def test_ceo_classify_action() -> None:
    assert classify_action("decide where to concentrate investment") is ActionClass.DIRECTIVE
    assert classify_action("audit the org and re-prioritise") is ActionClass.DIRECTIVE
    assert classify_action("hire two engineers next quarter") is ActionClass.COMMIT
    assert classify_action("ship to production on Friday") is ActionClass.COMMIT


def test_ceo_skills_exist_on_disk() -> None:
    import chorus_employee.ceo as ceo_pkg

    skills_root = Path(ceo_pkg.__file__).parent / "skills"
    for skill in ceo_plugin().manifest.skills:
        assert (skills_root / skill / "SKILL.md").is_file(), f"missing skill {skill}"
    assert len(ceo_plugin().manifest.skills) >= 5


def test_default_workforce_registers_the_ceo_from_here() -> None:
    assert "ceo" in {p.name for p in default_roles()}
    assert "ceo" in {p.name for p in default_employees()}
