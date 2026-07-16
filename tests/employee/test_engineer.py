"""The Engineer employee config — a complete dream harness, every component declared.

These tests pin the engineer as the first employee to own a dedicated package
(``chorus_employee/engineer/``). They assert the config carries *every*
``build_harness`` component, and that the legacy plugin remains available for explicit registration.
"""

from __future__ import annotations

import pytest

from chorus.roles import default_roles, role_beat_config
from chorus_employee import default_employees, engineer_plugin

pytestmark = pytest.mark.unit


def test_engineer_declares_every_build_harness_component() -> None:
    manifest = engineer_plugin().manifest
    # Capability components.
    assert manifest.tools == (
        "read_file",
        "write_file",
        "run_command",
        "git",
        "todo_write",
        "skill",
        "memory_search",
        "memory_get",
        "working_memory_read",
        "working_memory_write",
        "working_memory_append",
        "memory_propose",
        "recall",
        "lattice_context",
        "lattice_packet",
        "lattice_apply",
        "skill_manage",
    )
    assert manifest.permission_mode.value == "acceptEdits"  # can write under its own posture
    assert manifest.memory_scope.value == "project"
    assert manifest.system_prompt  # a real operating brief, not a placeholder
    # Engine scalars — every remaining build_harness knob is explicitly set.
    assert manifest.max_turns >= 8  # coding is multi-step; at least dream's default
    assert manifest.working_memory is True  # the engineer keeps a task scratchpad
    assert manifest.model is None  # uses the deployment model the composition root supplies
    assert manifest.mcp is False and manifest.plugins is False  # opt-in surfaces, off by default


def test_engineer_projects_to_a_beat_config_carrying_the_scalars() -> None:
    config = role_beat_config(engineer_plugin().manifest)
    assert "memory_search" in config.tools
    assert "working_memory_write" in config.tools
    assert config.permission_mode == "acceptEdits"
    assert config.max_turns >= 8
    assert config.working_memory is True


def test_engineer_ships_its_dod_and_outcome() -> None:
    plugin = engineer_plugin()
    assert plugin.name == "engineer"
    assert plugin.outcome_kind == "pr"
    verifier = plugin.dod_generator("implement the thing")
    assert verifier is not None  # a typed Verifier, not None/str


def test_legacy_engineer_plugin_remains_available_for_explicit_registration() -> None:
    assert engineer_plugin().name == "engineer"
    assert "engineer" not in {role.name for role in default_roles()}


def test_default_employees_uses_specific_engineering_professions() -> None:
    names = {r.name for r in default_employees()}
    assert {"backend_engineer", "frontend_engineer", "pm", "analyst"} <= names
    assert names.isdisjoint({"engineer", "reviewer"})
    assert "manager" not in names
