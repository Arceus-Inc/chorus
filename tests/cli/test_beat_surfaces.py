"""CLI beat composition can opt Backend Engineer into Dream surfaces."""

from __future__ import annotations

import pytest

from chorus_cli._beats import default_roles_from_env

pytestmark = pytest.mark.unit


def _engineer():
    return next(plugin for plugin in default_roles_from_env() if plugin.name == "backend_engineer")


def test_empty_surfaces_env_keeps_engineer_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHORUS_ENGINEER_SURFACES", raising=False)
    engineer = _engineer()

    # The engineer ships default skills (M8 profession playbooks; cross-beat orientation ships
    # via the factory's shared skills roots) — the env override adds surfaces on top of that
    # default, it no longer defines it. Assert the intent: discovery stays ON by default.
    assert engineer.manifest.skills
    assert engineer.manifest.mcp is False
    assert engineer.manifest.plugins is False


def test_surfaces_env_enables_requested_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHORUS_ENGINEER_SURFACES", " skills, mcp, plugins ")
    engineer = _engineer()

    # skills=True guarantees a NON-EMPTY tuple (discovery on); the ("project",) placeholder only
    # fills a previously-empty tuple, and the engineer's default tuple is no longer empty.
    assert engineer.manifest.skills
    assert "skill" in engineer.manifest.tools
    assert engineer.manifest.mcp is True
    assert engineer.manifest.plugins is True
