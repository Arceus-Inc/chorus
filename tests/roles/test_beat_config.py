"""RoleBeatConfig — the dream-free, beat-ready projection of a role (spec 06 §2, spec 05).

The agnostic seam: any front end (the public API, the CLI chat) resolves an employee's role to this
config without importing dream. The composition root then turns it into a concrete dream harness. The
tool names stay *chorus* names here (``run_command``, …) — the chorus→dream mapping is the seam's job.
"""

from __future__ import annotations

import pytest

from chorus.roles import RoleManifest, role_beat_config
from chorus.roles._manifest import MemoryScope, PermissionMode

pytestmark = pytest.mark.unit


def test_projects_the_manifest_fields_the_beat_needs() -> None:
    manifest = RoleManifest(
        system_prompt="You implement and ship changes.",
        tools=("read_file", "write_file", "run_command", "git"),
        permission_mode=PermissionMode.ACCEPT_EDITS,
        memory_scope=MemoryScope.PROJECT,
    )
    config = role_beat_config(manifest)
    assert config.system_prompt == "You implement and ship changes."
    assert config.tools == ("read_file", "write_file", "run_command", "git")
    assert config.permission_mode == "acceptEdits"  # dream-compatible string, not the enum
    assert config.memory_scope == "project"
    assert config.isolation == "worktree"  # the containment posture, as a plain string
    assert config.sandbox == "repo-write"  # the trust posture (dream sandbox tier), as a plain string


def test_permission_modes_map_to_dream_strings() -> None:
    for mode, expected in [
        (PermissionMode.DEFAULT, "default"),
        (PermissionMode.ACCEPT_EDITS, "acceptEdits"),
        (PermissionMode.PLAN, "plan"),
        (PermissionMode.DONT_ASK, "dontAsk"),
    ]:
        config = role_beat_config(RoleManifest(system_prompt="x", permission_mode=mode))
        assert config.permission_mode == expected


def test_config_is_frozen_and_hashable() -> None:
    config = role_beat_config(RoleManifest(system_prompt="x", tools=("read_file",)))
    assert hash(config)  # safe to share across async beats


def test_projects_every_build_harness_scalar() -> None:
    manifest = RoleManifest(
        system_prompt="x",
        model="gpt-eng",
        max_turns=12,
        working_memory=True,
        wake_model="gpt-cheap",
        mcp=True,
        plugins=True,
        env=(("DREAM_HOME", "/tmp/h"),),
    )
    config = role_beat_config(manifest)
    assert config.model == "gpt-eng"
    assert config.max_turns == 12
    assert config.working_memory is True
    assert config.wake_model == "gpt-cheap"
    assert config.mcp is True
    assert config.plugins is True
    assert config.env == (("DREAM_HOME", "/tmp/h"),)


def test_scalar_defaults_match_a_lean_harness() -> None:
    config = role_beat_config(RoleManifest(system_prompt="x"))
    assert config.model is None  # None → use the deployment model
    assert config.max_turns == 8  # dream's default
    assert config.working_memory is False
    assert config.mcp is False and config.plugins is False  # opt-in
    assert config.env == ()
