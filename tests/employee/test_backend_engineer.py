"""The Backend Engineer walking skeleton (backend-engineer spec §16 Slice 1) — the employee scaffold.

Deterministic (no LLM): the plugin resolves, its manifest carries the build-and-run toolset + the
``UNRESTRICTED`` sandbox + worktree isolation, its DoD is a reviewed build landing a ``pr``, and the
kernel registers it by default (single source — no drift). The live LLM beat that actually implements
and lands a tiny service is exercised opt-in by ``examples/backend_engineer_live_smoke.py``.
"""

from __future__ import annotations

import pytest

from chorus.outcomes import DoDKind
from chorus.roles import default_roles, role_beat_config
from chorus.roles._manifest import Isolation, PermissionMode, SandboxTier
from chorus_employee.backend_engineer import backend_engineer_plugin

pytestmark = pytest.mark.unit


def test_manifest_carries_the_build_and_run_toolset() -> None:
    manifest = backend_engineer_plugin().manifest
    # The build-and-prove toolset: it must read/write code, run arbitrary commands, and use git.
    for tool in ("read_file", "write_file", "run_command", "git"):
        assert tool in manifest.tools
    assert manifest.system_prompt  # a real operating brief, not a placeholder


def test_manifest_is_unrestricted_in_a_worktree() -> None:
    manifest = backend_engineer_plugin().manifest
    # The distinctive posture (§07): install + run arbitrary build/test commands, contained + reversible.
    assert manifest.sandbox is SandboxTier.UNRESTRICTED
    assert manifest.isolation is Isolation.WORKTREE
    assert manifest.permission_mode is PermissionMode.ACCEPT_EDITS
    assert manifest.working_memory is True  # a scratchpad across the implement→run→fix turns
    assert manifest.max_turns >= 12  # implement → run → fix is turn-hungry
    assert manifest.model is None  # uses the deployment model the composition root supplies


def test_dod_is_a_reviewed_build_landing_a_pr() -> None:
    plugin = backend_engineer_plugin()
    assert plugin.name == "backend_engineer"
    assert plugin.outcome_kind == "pr"
    verifier = plugin.dod_generator("add an idempotent endpoint")
    assert verifier.kind is DoDKind.REVIEWED_BUILD
    assert verifier.artifact_class == "pr"


def test_projects_to_a_beat_config_carrying_the_toolset() -> None:
    config = role_beat_config(backend_engineer_plugin().manifest)
    assert "run_command" in config.tools
    assert config.permission_mode == "acceptEdits"
    assert config.sandbox == "unrestricted"


def test_registered_in_default_roles() -> None:
    names = {plugin.name for plugin in default_roles()}
    assert "backend_engineer" in names
    # And the pr lander already handles it — outcome_kind matches the Engineer's, no new lander needed.
    assert backend_engineer_plugin().outcome_kind == "pr"
